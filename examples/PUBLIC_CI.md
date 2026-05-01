# Public-CI examples

Each `<owner>__<repo>` subdirectory in `examples/` (alongside this file)
holds a real `.gitlab-ci.yml` snapshot from a public GitLab project,
mirrored to GitHub at the time of fetch. Browse them with `sim-web`, or
use them as a smoke-test corpus — the engine compiles every one into a
non-empty Pipeline without raising (covered by
`src/web/tests/test_public_ci.py`).

Refresh with `scratch/fetch_probes.sh` then `scratch/install_fixtures.sh`.

| Slug | Source (raw github mirror) |
|------|-----------------------------|
| `buildroot__buildroot` | https://raw.githubusercontent.com/buildroot/buildroot/master/.gitlab-ci.yml |
| `gnome__glibmm` | https://raw.githubusercontent.com/GNOME/glibmm/master/.gitlab-ci.yml |
| `gnome__pango` | https://raw.githubusercontent.com/GNOME/pango/main/.gitlab-ci.yml |
| `gnome__gtkmm` | https://raw.githubusercontent.com/GNOME/gtkmm/master/.gitlab-ci.yml |
| `gnome__libxslt` | https://raw.githubusercontent.com/GNOME/libxslt/master/.gitlab-ci.yml |
| `wireshark__wireshark` | https://raw.githubusercontent.com/wireshark/wireshark/master/.gitlab-ci.yml |
| `gnome__gnome-online-accounts` | https://raw.githubusercontent.com/GNOME/gnome-online-accounts/master/.gitlab-ci.yml |
| `gnome__glib` | https://raw.githubusercontent.com/GNOME/glib/main/.gitlab-ci.yml |
| `gnome__gnome-system-monitor` | https://raw.githubusercontent.com/GNOME/gnome-system-monitor/master/.gitlab-ci.yml |
| `gnome__gobject-introspection` | https://raw.githubusercontent.com/GNOME/gobject-introspection/main/.gitlab-ci.yml |
