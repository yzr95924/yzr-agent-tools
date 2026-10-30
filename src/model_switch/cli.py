"""argparse-based CLI for model-switch.

The registry (``models.toml``) maps ``yzr-*`` provider IDs onto built-in
OpenCode providers through ``canonical_provider``. Every write mirrors it into
``opencode.json``; model definitions themselves are inherited from OpenCode,
never copied into the registry.

Output goes to stdout; errors to stderr. Exit codes:
  0 = success
  1 = user error (bad reference, missing credentials, unresolved catalog)
  2 = argparse error (unknown command / flag)
"""
import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from model_switch import catalog, opencode, paths, store, ui


def _die(message) -> None:
    ui.fail(message)


def _interactive(args: argparse.Namespace) -> bool:
    """True when we may prompt: a TTY and no blanket ``--yes``."""
    return sys.stdin.isatty() and not args.yes


def _prompt(label: str) -> str:
    """Read one required line from stdin (interactive only)."""
    if not sys.stdin.isatty():
        _die("{!r} is required (no TTY for interactive prompt). "
             "Pass it as a flag.".format(label))
    while True:
        try:
            line = input("{}: ".format(label))
        except EOFError:
            _die("{!r} is required (input exhausted). Pass it as a "
                 "flag.".format(label))
        if line == "":
            _die("value is required.")
        return line


def _prompt_secret(label: str) -> str:
    """Read the API key. It is persisted in plaintext anyway, so echo it."""
    if not sys.stdin.isatty():
        _die("{} is required (no TTY for prompt). Pass it via "
             "--api-key.".format(label))
    try:
        value = input("{}: ".format(label))
    except EOFError:
        _die("{} is required (input exhausted). Pass it via "
             "--api-key.".format(label))
    if value == "":
        _die("value is required.")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-switch",
        description="Switch OpenCode models through yzr-* canonical aliases.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    p_model = sub.add_parser("model", help="Manage model aliases.")
    model_sub = p_model.add_subparsers(
        dest="model_action", required=True, metavar="ACTION")

    p_add = model_sub.add_parser("add", help="Add or replace a model alias.")
    p_add.add_argument(
        "ref", nargs="?", default=None,
        help="Model reference: yzr-provider/model (e.g. yzr-zai/glm-5.3).",
    )
    p_add.add_argument("--api-key", default=None,
                       help="API key (stored plaintext in models.toml).")
    p_add.add_argument(
        "--catalog-provider", default=None,
        help="Pin the built-in provider a new yzr-* group inherits from.",
    )
    p_add.add_argument(
        "--yes", "-y", action="store_true",
        help="Assume yes: skip the confirmation and overwrite an existing "
             "model of the same reference.",
    )

    model_sub.add_parser("list", help="List all configured model aliases.")

    p_show = model_sub.add_parser("show", help="Show one alias as JSON.")
    p_show.add_argument("ref", nargs="?", default=None)

    p_rm = model_sub.add_parser("remove", help="Remove a model alias.")
    p_rm.add_argument("ref", nargs="?", default=None)
    p_rm.add_argument("--yes", "-y", action="store_true",
                      help="Skip the removal confirmation.")

    p_use = model_sub.add_parser("use", help="Activate a model alias.")
    p_use.add_argument("ref", nargs="?", default=None)

    p_align = model_sub.add_parser(
        "align",
        help="Check canonical sources against OpenCode's catalog cache.",
    )
    p_align.add_argument(
        "ref", nargs="?", default=None,
        help="Model to align; omit to align every model.",
    )

    sub.add_parser("status", help="Show the current OpenCode state.")

    p_complete = sub.add_parser("_complete")
    p_complete.add_argument(
        "what", choices=["models"],
        help="Which candidates to print, one per line.",
    )
    return parser


# --- shared helpers -----------------------------------------------------------


def _load_registry() -> Dict[str, Any]:
    return store.load_models(paths.models_file())


def _resolve_ref_arg(ref: Optional[str], reg: Dict[str, Any]) -> str:
    """`ref`, or the interactive picker when omitted (never blocks non-TTY)."""
    if ref is not None:
        return ref
    if not sys.stdin.isatty():
        _die("model reference is required (no TTY for the picker) — pass "
             "yzr-provider/model as an argument.")
    refs = list(store.iter_refs(reg))
    if not refs:
        _die("no models configured — run `model-switch model add` first.")
    return refs[ui.pick_one("Configured models:", refs)]


def _split_or_die(ref: str):
    try:
        return store.split_ref(ref)
    except store.StoreError as e:
        _die(e)


def _sync(data: Dict[str, Any], create: bool = False) -> None:
    try:
        opencode.sync(data, create=create)
    except store.StoreError as e:
        _die(e)


def _save(reg: Dict[str, Any]) -> None:
    try:
        store.save_models(paths.models_file(), reg)
    except store.StoreError as e:
        _die(e)


# --- model add ----------------------------------------------------------------


def _print_add_summary(ref: str, canonical: str, base_url: str,
                       api_key: str, replacing: bool) -> None:
    provider, model_id = ref.split("/", 1)
    print("")
    print("About to add {}{}".format(
        ref, " (replaces existing)" if replacing else ""))
    print("  provider          {}".format(provider))
    print("  canonical source  {}".format(canonical))
    print("  base URL          {}".format(base_url))
    print("  API key           <len {}>".format(len(api_key)))
    print("  model             {}".format(model_id))


def _do_model_add(args: argparse.Namespace) -> None:
    reg = _load_registry()
    ref = args.ref
    if ref is None:
        ref = _prompt("Model reference (yzr-provider/model)")
    provider, model_id = _split_or_die(ref)
    if not provider.startswith("yzr-"):
        _die("provider {!r} must start with 'yzr-'".format(provider))

    siblings = store.entries_for_provider(reg, provider)
    api_key = args.api_key or (siblings[0].get("api_key") if siblings else None)
    if not api_key:
        api_key = _prompt_secret("API key")

    data, desc = catalog.load_cache()
    if data is None:
        _die("{}; cannot add an alias without it.".format(desc))

    if siblings:
        canonical = siblings[0]["canonical_provider"]
        if args.catalog_provider is not None and args.catalog_provider != canonical:
            _die("--catalog-provider {!r} conflicts with the existing "
                 "canonical source {!r} of {}.".format(
                     args.catalog_provider, canonical, provider))
        candidate = catalog.lookup(data, canonical, model_id)
        if candidate is None:
            _die("canonical provider {!r} does not serve {!r} over a "
                 "chat-completions default route".format(canonical, model_id))
        if candidate.base_url != siblings[0]["base_url"]:
            _die("{} uses a drifted base URL; run `model-switch model align` "
                 "before adding models to it.".format(provider))
        base_url = siblings[0]["base_url"]
    else:
        cands = catalog.model_candidates(data, model_id)
        picked = catalog.pick(cands, args.catalog_provider)
        if picked.candidate is None:
            names = ", ".join(c.provider for c in picked.alternatives)
            detail = picked.reason
            if names:
                detail += " (candidates: {})".format(names)
            if picked.alternatives:
                detail += "; pin one with --catalog-provider <id>"
            _die("cannot resolve {}: {}".format(model_id, detail))
        candidate = picked.candidate
        canonical = candidate.provider
        base_url = candidate.base_url

    replacing = any(e.get("model_id") == model_id for e in siblings)
    if _interactive(args):
        _print_add_summary(ref, canonical, base_url, api_key, replacing)
        if not ui.confirm("Proceed?", default=True):
            ui.abort("Aborted — nothing written.")

    reg.setdefault("models", [])
    reg["models"] = [e for e in reg["models"]
                     if not (e.get("provider") == provider
                             and e.get("model_id") == model_id)]
    reg["models"].append({
        "model_id": model_id,
        "provider": provider,
        "canonical_provider": canonical,
        "base_url": base_url,
        "api_key": api_key,
    })

    _save(reg)
    _sync(reg, create=True)
    print("{} model {}.".format("Replaced" if replacing else "Added", ref))


# --- read-only commands -------------------------------------------------------


def _do_model_list() -> None:
    reg = _load_registry()
    if not reg.get("models"):
        print("(no models configured — run `model-switch model add` to add one)")
        return
    active = reg.get("active_model")
    for pid in store.provider_labels(reg):
        entries = store.entries_for_provider(reg, pid)
        first = entries[0]
        print("{}  <- {}  {}".format(
            pid, first["canonical_provider"], first["base_url"]))
        for entry in entries:
            ref = "{}/{}".format(pid, entry["model_id"])
            marker = "→" if ref == active else " "
            print("  {} {}".format(marker, ref))


def _do_model_show(args: argparse.Namespace) -> None:
    reg = _load_registry()
    ref = _resolve_ref_arg(args.ref, reg)
    entry = store.get_model(reg, ref)
    if entry is None:
        _die("model {!r} not found.".format(ref))
    payload = {
        "provider": {
            "canonical_provider": entry["canonical_provider"],
            "base_url": entry["base_url"],
            "api_key": "<set>" if entry.get("api_key") else "<missing>",
        },
        "model": {"model_id": entry["model_id"]},
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _do_status() -> None:
    reg = _load_registry()
    active = reg.get("active_model")
    print("model-switch status")
    print("----------------------")
    print("active model:  {}".format(active or "(none)"))
    print("registry:      {} ({} provider(s), {} model(s))".format(
        paths.models_file(), len(store.provider_labels(reg)),
        len(reg.get("models") or [])))
    print("opencode:      {}".format(paths.opencode_config_file()))
    labels = store.provider_labels(reg)
    if labels:
        print("providers:     {}".format(", ".join(labels)))


# --- mutating commands --------------------------------------------------------


def _do_model_remove(args: argparse.Namespace) -> None:
    reg = _load_registry()
    ref = _resolve_ref_arg(args.ref, reg)
    entry = store.get_model(reg, ref)
    if entry is None:
        _die("model {!r} not found.".format(ref))
    if _interactive(args):
        if not ui.confirm("Remove model {!r}?".format(ref), default=False):
            ui.abort("Aborted — nothing removed.")
    reg["models"].remove(entry)
    if reg.get("active_model") == ref:
        del reg["active_model"]
    _save(reg)
    _sync(reg, create=False)
    print("Removed model {}.".format(ref))


def _do_model_use(args: argparse.Namespace) -> None:
    reg = _load_registry()
    ref = _resolve_ref_arg(args.ref, reg)
    if store.get_model(reg, ref) is None:
        _die("model {!r} not found.".format(ref))
    reg["active_model"] = ref
    _save(reg)
    _sync(reg, create=True)
    print("Switched to {}.".format(ref))
    print("  OpenCode default: {}".format(ref))
    print("  Configuration reloads automatically; sessions in flight keep "
          "their settings.")


# --- align --------------------------------------------------------------------


def _do_model_align(args: argparse.Namespace) -> int:
    reg = _load_registry()
    if args.ref is not None and store.get_model(reg, args.ref) is None:
        _die("model {!r} not found.".format(args.ref))
    targets = [args.ref] if args.ref is not None else list(store.iter_refs(reg))
    if not targets:
        _die("models.toml declares no models.")

    data, desc = catalog.load_cache()
    if data is None:
        _die("{}; cannot align without it.".format(desc))

    width = max(len(r) for r in targets)
    changed = 0
    skipped = 0
    for ref in targets:
        entry = store.get_model(reg, ref)
        candidate = catalog.lookup(
            data, entry["canonical_provider"], entry["model_id"])
        if candidate is None:
            skipped += 1
            print("{:<{w}}  skip  {} no longer serves {!r} over a "
                  "chat-completions default route".format(
                      ref, entry["canonical_provider"], entry["model_id"],
                      w=width))
            continue
        changes = []
        if candidate.base_url != entry["base_url"]:
            entry["base_url"] = candidate.base_url
            changes = ["base_url"]
        if changes:
            changed += 1
        print("{:<{w}}  {:<7}  {}  {}".format(
            ref, "aligned" if changes else "ok",
            entry["canonical_provider"],
            ", ".join(changes) or "no change", w=width))

    if changed:
        _save(reg)
        _sync(reg, create=False)
    print("align: {} updated, {} skipped (of {}) via {}".format(
        changed, skipped, len(targets), desc))
    return 1 if skipped else 0


# --- completion plumbing ------------------------------------------------------


def _do_complete_models() -> None:
    reg = _load_registry()
    for ref in store.iter_refs(reg):
        print(ref)


# --- dispatch -----------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        ui.abort("Aborted.", code=130)
    except store.StoreError as e:
        _die(e)


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "model":
        if args.model_action == "add":
            _do_model_add(args)
        elif args.model_action == "list":
            _do_model_list()
        elif args.model_action == "show":
            _do_model_show(args)
        elif args.model_action == "remove":
            _do_model_remove(args)
        elif args.model_action == "use":
            _do_model_use(args)
        elif args.model_action == "align":
            return _do_model_align(args)
        return 0
    if args.cmd == "status":
        _do_status()
        return 0
    if args.cmd == "_complete":
        _do_complete_models()
    return 0


if __name__ == "__main__":
    sys.exit(main())
