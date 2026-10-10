# Yumi

This distribution installs `yumi-agent`, which owns the `yumi` command and all
Python modules. It contains no duplicate modules or command entry points.

```sh
pip install yumi
yumi --voice
```

Choose your local Yumi server or sign in to Yumi Nexus, then say **Hey Yumi**.
First-run wake-model setup is automatic. See the
[voice guide](https://github.com/wenxijiao/yumi-agent/blob/main/docs/HEY_YUMI_VOICE_CLIENT.md).

Release maintainers: this alias must only be published after the matching
`yumi-agent` release. The PyPI `yumi` project needs its own Trusted Publisher
for `release-alias.yml`; namespace availability/ownership must be established
on PyPI. Building this directory does not publish or reserve that name.
