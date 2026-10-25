# Running the oil-price experiments on Iridis

How [experiments/levy_fourier.py](../experiments/levy_fourier.py) was run on the University of
Southampton's Iridis X cluster, and the things that tripped us up. The job scripts are in
[cluster/iridis/](../cluster/iridis/).

## Access

- Off campus, connect the university VPN (GlobalProtect) first. The login node names
  (`loginx001`–`loginx003.iridis.soton.ac.uk`) only resolve on the university network.
- Log in with SSH keys and your university username. An `~/.ssh/config` entry
  (`Host iridis`, `HostName loginx001.iridis.soton.ac.uk`, `User <username>`,
  `IdentityFile ~/.ssh/id_ed25519`) makes `ssh iridis` work.
- Work under `/scratch/$USER`; home has a small quota. `scripts/hpc_env.sh` moves uv's cache and
  Python downloads to scratch.

## From the laptop in one command

[cluster/iridis/run.sh](../cluster/iridis/run.sh) does the copy, submit and fetch for any
experiment command, so nothing heavy has to run on the laptop:

```bash
bash cluster/iridis/run.sh submit goods "experiments/sector_global.py fold "{0..7}" --set goods" \
    "experiments/sector_global.py benchmarks --set goods"
bash cluster/iridis/run.sh wait goods    # blocks until the tasks finish, then copies outputs back
```

- `submit <tag> <command>...` copies the current checkout's working tree (uncommitted edits
  included) to a new `/scratch/$USER/oxhack-<tag>` and submits one array task per command. Each
  command is the arguments to python. It refuses a tag that already exists, so each code version
  gets its own folder. `SOURCE.txt` in that folder records the branch, commit and uncommitted
  files.
- `wait <tag>` / `fetch <tag>` copy back what the tasks wrote under `runs/`. A local file they
  replace is kept in `runs/iridis/<tag>/replaced/`, and the Slurm logs go to `runs/iridis/<tag>/`.
  `status <tag>` shows the queue and exit states. `runs/iridis/jobs.tsv` lists every submission.
- `CPUS`, `MEM`, `TIME`, `PARTITION` and `VENV` set the resources and the venv (default
  `../oxhack-chain/.venv-nn`, built by `cluster/iridis/macro_env.sh`). `IRIDIS` is the ssh target,
  default `iridis` (the `~/.ssh/config` alias under Access).

## One-time setup (login node; compute nodes have no internet)

```bash
mkdir -p /scratch/$USER/oxhack && cd /scratch/$USER/oxhack
# copy experiments/, cluster/, scripts/ and data/raw/DCOILBRENTEU.csv up from the laptop, e.g.
#   tar czf - experiments cluster scripts data/raw/DCOILBRENTEU.csv | ssh iridis 'cd /scratch/$USER/oxhack && tar xzf -'
bash cluster/iridis/levy_env.sh      # makes .venv-levy with numpy, scipy, pandas
```

Copy the laptop's data file rather than re-downloading, so both sides use the same vintage
(compare `md5sum data/raw/DCOILBRENTEU.csv`).

## Runs

```bash
sbatch --array=0-29 cluster/iridis/levy.slurm                  # GARCH family
FAMILY=iid sbatch --array=0-29 cluster/iridis/levy.slurm       # constant-sigma family
```

- Task 0 runs the self-checks and then the fixed split (train before 2008-10-15, test after).
  Tasks 1–29 are the rolling refits for 1998–2026.
- `PATHS` (default 20,000) sets the simulated paths per forecast origin.
- Outputs go to `runs/levy/*.json` (git-ignored). Copy them back and run
  `uv run experiments/levy_fourier.py report` to write `notes/levy-fourier-results.md`.
- **Timing:** about 13 minutes for task 0 and 4–5 minutes for a rolling year, on 2 cores and
  under 8 GB. The `amd_student` partition ran 10 of our tasks at a time, so two 30-task arrays
  took about 35 minutes.
- **Code versions:** when changing code mid-run, deploy it to a new folder
  (`/scratch/$USER/oxhack-v2`, `-v3`, ...) and point `PY=` at the existing venv. Queued tasks
  read the Python file when they start, so overwriting it in place mixes versions.

## Gotchas we hit

- `sbatch` refuses a job without `--nodes`; the scripts set it, and so must any `--wrap` job.
- `uv`, `sbatch` and `squeue` are only on the `PATH` in a login shell (`bash -lc "..."`).
- Shell and Slurm scripts must have LF line endings. `.gitattributes` forces that on Windows
  checkouts.
- Check the "Fit health" line at the top of the report. It flags any run whose daily log density
  goes above 8, which can only happen if a fit has collapsed. That is how the off-grid density bug
  described in [oil-price-model.md](oil-price-model.md) was caught.
- A venv built with `uv venv --python 3.12` can link to the login node's `/usr/bin/python3.12`,
  which compute nodes don't have; every task then fails in under a second with "No such file or
  directory". Set `UV_PYTHON_INSTALL_DIR` to scratch and pass `--python-preference only-managed`
  (as `cluster/iridis/cost_of_living_env.sh` does), then check `readlink -f .venv-*/bin/python`.
- A pipe hides a failed setup step: `bash env.sh | tail -3 && sbatch ...` submits even when the
  environment build failed, because the pipeline's status is `tail`'s. Build first, then submit.

## Cost-of-living basket model

`cluster/iridis/cost_of_living.slurm` runs one fit per array task (`--array=0-10`: the 2026 and
2022 event tests, the all-data fit and folds 0–7). It needs `data/raw/` and the stored daily Lévy
fits `runs/levy/rolling-*.json` copied up, and its own environment
(`bash cluster/iridis/cost_of_living_env.sh`, numpy, pandas, scipy, jax, numpyro; no PyTorch).
Each fit took 1–2 minutes on 4 cores. See [cost-of-living.md](cost-of-living.md).
