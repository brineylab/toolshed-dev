set -eu
out=$(hello)
echo "$out"
case "$out" in *"os="*"user="*"gpu="*) ;; *) exit 1 ;; esac
