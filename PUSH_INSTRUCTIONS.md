# Pushing this repo to GitHub

This is a fully-initialized git repo with a single commit on `main` and
a `v0.1.0` tag. To put it on GitHub, extract the tarball and pick one
of the paths below.

## Path A — using the GitHub CLI (recommended)

```bash
tar -xzf rescue-bird.tar.gz
cd rescue-bird

# One command — creates the repo and pushes everything including tags.
gh repo create kylefoxaustin/rescue-bird --public --source=. --push
git push origin v0.1.0
```

## Path B — plain git, you create the repo via web UI

1. Go to https://github.com/new, create empty repo `kylefoxaustin/rescue-bird`
   (don't initialize with README/license — they're already in the tarball)
2. Then:

```bash
tar -xzf rescue-bird.tar.gz
cd rescue-bird
git remote add origin git@github.com:kylefoxaustin/rescue-bird.git
git push -u origin main
git push origin v0.1.0
```

## Path C — first push to a private repo

Same as A but:

```bash
gh repo create kylefoxaustin/rescue-bird --private --source=. --push
git push origin v0.1.0
```

## Verifying the tarball before pushing

```bash
tar -xzf rescue-bird.tar.gz
cd rescue-bird

# Confirm git history is preserved
git log --oneline
git tag                    # should show v0.1.0
git status                 # should show clean working tree

# Run the tests to confirm nothing broke in transit
pip install pytest pyarrow pandas numpy pyyaml tabulate
pytest tests/ -v           # should report 59 passed

# Try the what-if engine
python -m instrumentation.analysis.whatif.whatif_cli point
```

## What's in the tarball

- 126 tracked files in the repo
- `.git/` directory with full commit history (preserved by tar)
- `v0.1.0` tag

## Author identity

The commit was made under the placeholder identity:
```
Kyle Fox <kyle@example.invalid>
```

After cloning, set your real identity for future commits:
```bash
git config user.email "your-actual@email.com"
git config user.name "Kyle Fox"
```

If you want to retroactively fix the author of the initial commit:
```bash
git commit --amend --reset-author --no-edit
git push --force-with-lease origin main    # only if already pushed
```
