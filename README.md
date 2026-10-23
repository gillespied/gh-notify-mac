# gh-notify

A macOS status bar app that raises native notifications for the GitHub things that
matter, so you can stop relying on noisy email:

- a review is requested from you
- someone comments on, or reviews, your pull requests
- someone replies to a comment you made
- someone @mentions you
- checks fail on your pull request

It polls GitHub using your existing `gh` login. No extra token is needed.

## Setup

Needs macOS, [uv](https://docs.astral.sh/uv/), the [GitHub CLI](https://cli.github.com/)
signed in (`gh auth login`), and the Xcode Command Line Tools (`clang`, `codesign`).

```sh
uv tool install .
gh-notify install      # builds ~/Applications/GH Notify.app, starts it, and keeps it alive
```

`install` works with uv-managed and Homebrew (framework) Python. If your Python is unusual and
`install` reports that libpython cannot be found, use a uv-managed one:
`uv tool install . --reinstall --python 3.13 --python-preference only-managed`.

Then allow notifications for **GH Notify** in System Settings > Notifications, and run
`gh-notify restart`, because a running copy does not pick up a new permission.

A bell appears in the menu bar. The first poll only records what already exists, so you
are not flooded at launch. After that, only new things alert.

## Using it

- The bell shows a count of unread items. Click it to see them, grouped by type.
- Clicking an item, or its notification, opens it in your browser and marks it read.
- **Mark all read**, **Review queue**, **Check now**, **Send test notification**,
  **Pause** and **Start at login** are in the menu.
- Review requests and failing checks clear themselves once they are no longer true.

### Icon states

Bell: nothing unread. Bell with badge and count: unread items. Pause: paused.
Warning triangle: the last poll failed (the menu shows why, for example `gh` signed out).

## Settings

Optional file `~/.config/gh-notify/config.toml`. Changes are read on the next poll.

```toml
poll_interval = 90          # seconds, minimum 30
review_requested = true
pr_feedback = true          # comments and reviews on your PRs
replies = true              # replies to threads you commented in
mentions = true
ci_failures = true
include_drafts = true       # review requests on draft PRs
ignore_bots = true
ignore_authors = []         # extra logins to ignore
gh_path = ""                # only if gh is somewhere unusual
paused = false
```

Replies are the noisiest event. Switch `replies` off first if it is too much.

## Commands

```sh
gh-notify check        # print what GitHub reports now (last 7 days), changes nothing
gh-notify install      # build the app bundle, load the LaunchAgent
gh-notify restart      # restart the agent (after reinstalling or changing permissions)
gh-notify status
gh-notify uninstall    # unload and remove the plist; keeps the app so permission survives
gh-notify -v run       # run in a terminal, only if the agent is not running
```

After code changes: `uv tool install . --reinstall && gh-notify install`. The launcher
records the Python and package paths, so re-run `install` whenever they change.

Logs: `~/Library/Logs/gh-notify.log`. State: `~/.config/gh-notify/state.json`.

## How it works

`gh auth token` supplies the token. Four GraphQL searches run one after another (review
requests, your open PRs, mentions, threads you commented in). `events.py` turns the
responses into events, `state.py` remembers which have been seen, and `poller.py` runs
this on a background thread with back-off on errors and rate limits.

macOS only delivers notifications from a process that belongs to an app bundle. A normal
Python interpreter has no bundle, so its notifications are silently dropped. `bundle.py`
builds `~/Applications/GH Notify.app` with a small C launcher that loads `libpython` into
its own process, so the process reports the bundle ID `com.gillespied.gh-notify`.

## Troubleshooting

- **No notifications:** check System Settings > Notifications > GH Notify, then
  `gh-notify restart`. The menu shows a warning if the app is not running inside its bundle.
- **Warning triangle:** open the menu to read the error. `gh auth login` fixes sign-in errors.
- **"already running":** only one copy can run. `gh-notify uninstall` first if you want a
  terminal copy.

## Development

```sh
uv run pytest
uv run ruff check .
```
