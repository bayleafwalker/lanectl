# PR landing for fan-out repos

Repos that merge through PRs and CI (homelab-analytics, sovite): `land` only
moves the local main. Then push the tip and merge with a merge commit, which
descends from the tip, so local main fast-forwards afterwards:

```sh
git -C <repo> push origin <tip>:refs/heads/lanes/<train_id>
gh pr create -R <owner/repo> -H lanes/<train_id> -t "<titles>" -b "<attempts, review notes>"
gh pr checks <n> -R <owner/repo> --watch && gh pr merge <n> -R <owner/repo> --merge --delete-branch
git -C <repo> pull --ff-only
```
Fetch and fast-forward the repo's main before writing releases for it, so the
train's base equals origin.
