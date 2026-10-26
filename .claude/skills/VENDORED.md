# Vendored design skills

Third-party agent skills copied into this repo so every Claude Code session on the project has them,
without a per-machine plugin install. Both are MIT-licensed; each folder keeps its `LICENSE`.
Do not edit them in place — update by re-copying from upstream at a newer commit.

| Skill | Source | Commit | Copied | Upstream path |
|---|---|---|---|---|
| `hallmark/` | https://github.com/Nutlope/hallmark | `7ec868225c6caa040558c321ee0fefa0e73f83a8` (2026-10-22) | 2026-10-26 | `skills/hallmark/` |
| `scroll-craft/` | https://github.com/nateherkai/scroll-craft | `75d81f74e83692add18cd7a8a8e078b8a887a579` (2026-09-30) | 2026-10-26 | `plugins/nateherk-design/skills/scroll-craft/` (+ root `LICENSE`) |

## Updating

```bash
git clone --depth 1 https://github.com/Nutlope/hallmark /tmp/hallmark
rm -r .claude/skills/hallmark && cp -r /tmp/hallmark/skills/hallmark .claude/skills/hallmark

git clone --depth 1 https://github.com/nateherkai/scroll-craft /tmp/scroll-craft
rm -r .claude/skills/scroll-craft && cp -r /tmp/scroll-craft/plugins/nateherk-design/skills/scroll-craft .claude/skills/scroll-craft
cp /tmp/scroll-craft/LICENSE .claude/skills/scroll-craft/LICENSE
```

Then update the commit and date in the table above, and read the upstream changes before committing —
these files are instructions every session will follow.

## Notes

- Neither skill's install script (`hallmark/scripts/install*.mjs`, `install-hook.mjs`) has been run: they
  would change user-level Claude Code settings. The skills work from this folder as they are.
- Optional paid asset generation needs a key (`TOGETHER_API_KEY` for Hallmark comps, `KIE_AI_API_KEY` for
  scroll-craft); without one both build from real data and supplied assets only.
