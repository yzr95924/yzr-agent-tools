#!/usr/bin/env zsh
# Capture the zsh completion candidates offered for one command line.
#
# Usage: zsh -f tests/zsh_capture.zsh <completions-dir> <input-line>
#
#   <input-line>  The line as typed; a trailing space means the next word is
#                 being completed, otherwise the last word is a partial token
#                 (candidates are prefix-filtered against it).
#
# Prints one candidate per line. Exit codes: 0 ok, 1 timeout, 64 usage.
#
# How it works: the completion machinery (_arguments/_describe/compadd) only
# runs inside a live line editor, so this driver spawns a real interactive
# zsh under zpty. The child rc points fpath at <completions-dir>, runs
# compinit, and installs a shadow `compadd` function that records every
# candidate the completion system offers instead of handing it to the editor;
# a comppostfunc dumps the capture between sentinel lines after one TAB.
#
# Accepted noise: the real compadd deduplicates matches internally, so the
# shadow may observe the same word from several internal rounds — the dump
# below dedupes preserving first-seen order. `_files -g` globs can also
# surface one unfiltered fallback round; file-completion tests should assert
# membership, not exact sets.

emulate -L zsh

local compdir input tmpdir
compdir=$1
input=$2
[[ -n $compdir && -n $input ]] || { print -u2 "usage: zsh_capture.zsh <completions-dir> <input-line>"; exit 64; }

tmpdir=$(mktemp -d) || exit 1
trap 'rm -rf "$tmpdir"' EXIT INT TERM

mkdir -p "$tmpdir/zdot"
cat > "$tmpdir/zdot/.zshrc" <<'RC'
PROMPT=''
RPROMPT=''
fpath=(__COMPDIR__ $fpath)
autoload -Uz compinit && compinit -D -u
typeset -ga ZCAP
ZCAP=()
compadd() {
  emulate -L zsh
  local -a argvs out vals
  local i c skip=0 dd=0 aflag=0 kflag=0 flags ch rest w v added
  local ARGFLAGS="FPSpsiIWdJXxVrRDOAME"
  argvs=("$@")
  out=()
  for (( i=1; i<=$#argvs; i++ )); do
    c=${argvs[i]}
    if (( skip )); then skip=0; continue; fi
    if (( dd )); then out+=("$c"); continue; fi
    case "$c" in
      -|--) dd=1 ;;
      -*)
        flags=${c#-}
        rest=$flags
        while [[ -n $rest ]]; do
          ch=${rest[1]}
          rest=${rest[2,-1]}
          if [[ $ch == a ]]; then
            aflag=1
          elif [[ $ch == k ]]; then
            kflag=1
          elif [[ $ARGFLAGS == *$ch* ]]; then
            [[ -z $rest ]] && skip=1
            break
          elif [[ $ch == o ]]; then
            # -o [order]: order is a separate word only when it does not
            # look like the next option (zshcompsys: compadd -o nosort ...).
            if [[ -z $rest ]] && (( i < $#argvs )) && [[ ${argvs[i+1]} != -* ]]; then
              skip=1
            fi
            break
          fi
        done
        ;;
      *) out+=("$c") ;;
    esac
  done
  added=0
  for w in "${out[@]}"; do
    vals=()
    if (( aflag )); then
      (( ${(P)+w} )) && vals=("${(@P)w}")
    elif (( kflag )); then
      vals=("${(@kP)w}")
    else
      vals=("$w")
    fi
    for v in "${vals[@]}"; do
      [[ -n $PREFIX && $v != ${PREFIX}* ]] && continue
      ZCAP+=("$v")
    done
  done
  # Note: compstate[nmatches] is read-only for compadd wrappers; leave it 0.
  return 0
}
comppostfuncs=(zcap_dump)
zcap_dump() {
  print -r -- "__ZCAP_BEGIN__"
  local -a seen
  local w
  seen=()
  for w in "${ZCAP[@]}"; do
    # Membership via subscript flags: [(Ie)w] gives the first matching index,
    # or 0 when absent — lowercase (ie) returns 1 on BOTH hit and miss (useless
    # here), and a plain [[ -z ${...} ]] test on "0" would drop every candidate.
    [[ -n $w ]] || continue
    if (( ! ${seen[(Ie)$w]} )); then
      seen+=("$w")
      print -r -- "$w"
    fi
  done
  print -r -- "__ZCAP_END__"
  ZCAP=()
}
bindkey '^I' complete-word
print -r -- "__READY__"
RC
local rccontent
rccontent=$(<"$tmpdir/zdot/.zshrc")
rccontent=${rccontent//__COMPDIR__/$compdir}
print -r -- "$rccontent" >! "$tmpdir/zdot/.zshrc"

zmodload zsh/zpty
export ZDOTDIR="$tmpdir/zdot"
zpty zcap "zsh -i"

local data="" chunk tries=0
while :; do
  zpty -r zcap chunk 2>/dev/null && data+=$chunk
  sleep 0.01
  (( ++tries > 600 )) && { print -u2 "timeout waiting for shell startup; saw: ${(q)data}"; exit 1; }
  [[ $data == *__READY__* ]] && break
done

zpty -w -n zcap "$input"$'\t'

data=""
tries=0
while :; do
  zpty -r zcap chunk 2>/dev/null && data+=$chunk
  sleep 0.01
  (( ++tries > 600 )) && {
    # Diagnostics: figure out whether the child is alive and where it is.
    # - ZLE disabled (e.g. TERM=dumb) swallows the TAB silently.
    # - a hung completion function also produces silence.
    print -u2 "timeout waiting for completion output; partial: ${(q)data}"
    zpty -w -n zcap $'\n'"print -r -- CHILD_ALIVE TERM=$TERM"\$'\n'
    local probe="" ptries=0
    while :; do
      zpty -r zcap chunk 2>/dev/null && probe+=$chunk
      sleep 0.01
      (( ++ptries > 200 )) && break
      [[ $probe == *CHILD_ALIVE* ]] && break
    done
    print -u2 "probe: ${(q)probe}"
    exit 1
  }
  [[ $data == *__ZCAP_END__* ]] && break
done

zpty -d zcap 2>/dev/null

print -r -- "$data" | sed -n '/__ZCAP_BEGIN__/,/__ZCAP_END__/p' | sed '1d;$d'
