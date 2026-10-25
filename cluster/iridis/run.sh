#!/usr/bin/env bash
# Run experiments on Iridis from the laptop. `submit` copies the current checkout's working tree
# (uncommitted edits included) to a new /scratch/$USER/oxhack-<tag> folder and submits one Slurm
# array task per command; `wait` blocks until they finish and copies their outputs back. Run it
# from the checkout whose code you want; the script itself can live in another checkout.
#   cluster/iridis/run.sh submit goods "experiments/sector_global.py fold "{0..7}" --set goods" \
#       "experiments/sector_global.py benchmarks --set goods"
#   cluster/iridis/run.sh status goods
#   cluster/iridis/run.sh wait goods     # then fetch: files the tasks wrote under runs/ land in runs/,
#                                        # the Slurm logs in runs/iridis/<tag>/
#   cluster/iridis/run.sh fetch goods    # fetch now, without waiting
# Each command is the arguments to python. Settings come from the environment: IRIDIS (ssh target,
# default "iridis", see docs/iridis.md), CPUS (4), MEM (8G), TIME (04:00:00), PARTITION
# (amd_student), VENV (venv on Iridis, relative to the run folder; default ../oxhack-chain/.venv-nn,
# built by cluster/iridis/macro_env.sh).
set -euo pipefail
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 "${IRIDIS:-iridis}")
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$(git rev-parse --show-toplevel)" && pwd)  # the checkout being run, as a /c/... path for tar
SHIP=(experiments cluster scripts data/raw notes/industry runs/levy)

die() { echo "run.sh: $*" >&2; exit 1; }
# a command in a login shell on Iridis (sbatch and squeue are only on the PATH there)
remote() { "${SSH[@]}" "bash -lc $(printf '%q' "$1")"; }

submit() {
    local tag=${1:-}; shift || true
    [[ $tag =~ ^[A-Za-z0-9._-]+$ ]] || die "usage: run.sh submit <tag> <command>..."
    [ $# -gt 0 ] || die "submit needs at least one command"
    local dir="/scratch/\$USER/oxhack-$tag"
    [ "$(remote "test -e $dir && echo taken || echo free")" = free ] \
        || die "oxhack-$tag already exists on Iridis (or Iridis is unreachable); use a new tag per code version"

    local stage paths=() p
    stage=$(mktemp -d)
    printf '%s\n' "$@" > "$stage/jobs.txt"
    cp "$HERE/run.slurm" "$stage/run.slurm"
    { echo "checkout: $REPO"
      echo "branch: $(git -C "$REPO" branch --show-current)"
      echo "commit: $(git -C "$REPO" rev-parse HEAD)"
      echo "shipped: $(date -u +%FT%TZ)"
      echo "uncommitted changes:"; git -C "$REPO" status --porcelain; } > "$stage/SOURCE.txt"
    for p in "${SHIP[@]}"; do [ -e "$REPO/$p" ] && paths+=("$p"); done
    tar czf - --exclude=__pycache__ -C "$REPO" "${paths[@]}" -C "$stage" jobs.txt run.slurm SOURCE.txt \
        | "${SSH[@]}" "mkdir -p $dir && tar xzf - -C $dir"
    rm -rf "$stage"

    local job
    job=$(remote "cd $dir && find . -name '*.sh' -o -name '*.slurm' -o -name jobs.txt | xargs sed -i 's/\r\$//' \
        && mkdir -p runs && ln -sfn ${VENV:-../oxhack-chain/.venv-nn} .venv-nn \
        && sbatch --parsable --job-name=oxh-$tag --array=0-$(($# - 1)) --cpus-per-task=${CPUS:-4} \
           --mem=${MEM:-8G} --time=${TIME:-04:00:00} --partition=${PARTITION:-amd_student} run.slurm | tee jobid")
    mkdir -p "$REPO/runs/iridis"
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$tag" "$job" "$(IFS='|'; echo "$*")" >> "$REPO/runs/iridis/jobs.tsv"
    echo "submitted job $job ($# tasks) in oxhack-$tag"
}

status() {
    remote "cd /scratch/\$USER/oxhack-$1 && j=\$(cat jobid) && squeue -h -j \$j -o '%i %T %M %R' 2>/dev/null; \
        sacct -n -X -j \$j -o JobID%16,State%12,Elapsed,ExitCode"
}

fetch() {
    local tag=$1 dest="$REPO/runs/iridis/$1" f
    mkdir -p "$dest"
    # what the tasks wrote: files under runs/ newer than jobs.txt (shipped files keep their old times)
    remote "cd /scratch/\$USER/oxhack-$tag && { find runs -type f -newer jobs.txt; ls slurm-*.out; } 2>/dev/null \
        | tar czf - -T -" | tar xzf - -C "$dest"
    # outputs go where the experiment scripts read them (a local file they replace is kept in
    # runs/iridis/<tag>/replaced/); the Slurm logs stay with the tag
    [ -d "$dest/runs" ] || { echo "no outputs yet"; return 0; }
    (cd "$dest" && find runs -type f | while read -r f; do
        if [ -e "$REPO/$f" ]; then mkdir -p "replaced/$(dirname "$f")" && mv -f "$REPO/$f" "replaced/$f"; fi
        mkdir -p "$REPO/$(dirname "$f")" && mv -f "$f" "$REPO/$f" && echo "fetched $f"; done)
    rm -rf "$dest/runs"
    echo "Slurm logs in runs/iridis/$tag/"
}

wait_done() {
    local tag=$1
    remote "test -s /scratch/\$USER/oxhack-$tag/jobid" || die "no job recorded in oxhack-$tag"
    # a dropped connection counts as still running, so the loop retries instead of fetching early
    until remote "cd /scratch/\$USER/oxhack-$tag && ! squeue -h -j \$(cat jobid) 2>/dev/null | grep -q ."; do
        sleep "${POLL:-60}"
    done
    status "$tag"
    fetch "$tag"
    if status "$tag" | grep -v COMPLETED | grep -q .; then die "some tasks did not complete (see runs/iridis/$tag/)"; fi
}

case ${1:-} in
    submit) shift; submit "$@" ;;
    status) status "${2:?tag}" ;;
    fetch) fetch "${2:?tag}" ;;
    wait) wait_done "${2:?tag}" ;;
    *) sed -n '2,15p' "$0"; exit 1 ;;
esac
