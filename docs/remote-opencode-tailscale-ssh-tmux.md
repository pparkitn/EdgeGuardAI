# Remote Control of OpenCode from a Phone with Tailscale, SSH, and tmux

This setup lets you remotely control a **running OpenCode terminal session** from a phone without installing a dedicated OpenCode mobile application.

The basic idea is simple:

```text
                    Tailscale
Phone ───────────────────────────────── Laptop
  │                                      │
  │ SSH                                  │
  ▼                                      ▼
SSH session                          tmux session
                                         │
                                         ▼
                                      OpenCode
                                         │
                                         ▼
                                   Project directory
```

The phone connects to the laptop over the private Tailscale network, opens an SSH session, and attaches to the same `tmux` terminal where OpenCode is running.

This means the phone is controlling the **actual OpenCode TUI session**, rather than creating a separate OpenCode web session.

---

## Why use this approach?

OpenCode can be used through a terminal, and a terminal session can be made remotely accessible with standard Linux tools.

This approach has several advantages:

- No dedicated OpenCode mobile application is required.
- No OpenCode web server is required.
- No router port forwarding is required.
- The existing OpenCode TUI workflow is preserved.
- The exact same running OpenCode session can be accessed from the laptop or phone.
- Multiple projects can have independent OpenCode sessions.
- `tmux` keeps OpenCode running even when the SSH connection or phone disconnects.
- Tailscale provides the private network connection between devices.

It is particularly useful when an OpenCode agent is running a long task and you want to check on it or respond to prompts while away from the laptop.

---

# Architecture

A typical setup looks like this:

```text
                         Private Tailscale Network
                  ┌─────────────────────────────────┐
                  │                                 │
             📱 Phone                         💻 Linux Laptop
                  │                                 │
                  │ SSH                             │
                  └───────────────────────────────►│
                                                    │
                                               tmux session
                                                    │
                                                    ▼
                                               OpenCode TUI
                                                    │
                                                    ▼
                                             Project directory
```

For multiple projects:

```text
Linux Laptop
│
├── tmux: project-a
│   └── OpenCode
│
├── tmux: project-b
│   └── OpenCode
│
├── tmux: project-c
│   └── OpenCode
│
└── tmux: project-d
    └── OpenCode
```

From the phone, you can list the running tmux sessions and attach to whichever project you need.

---

# 1. Install Tailscale

Install Tailscale on both:

- the Linux laptop running OpenCode
- the phone

Sign both devices into the same Tailscale account/tailnet.

Tailscale creates a private network between the devices.

The important security property is that SSH does **not** need to be exposed to the public Internet.

You do not need to:

- forward port 22 on your router
- expose SSH directly to the Internet
- configure a public DNS name

---

# 2. Install and enable SSH on Linux

On Debian/Ubuntu-based Linux:

```bash
sudo apt update
sudo apt install openssh-server
```

Check that SSH is running:

```bash
sudo systemctl status ssh
```

If necessary:

```bash
sudo systemctl enable --now ssh
```

From another device on the Tailscale network, SSH to the laptop using its Tailscale hostname or Tailscale address:

```bash
ssh <linux-user>@<tailscale-hostname>
```

Use your own username and Tailscale hostname. Do not publish credentials, private keys, host-specific addresses, or passwords in project documentation.

---

# 3. Install tmux

On the Linux laptop:

```bash
sudo apt install tmux
```

Check the installation:

```bash
tmux -V
```

`tmux` is what makes the terminal persistent.

Without tmux:

```text
Phone
  │
  └── SSH ──► terminal ──► OpenCode
                  │
             connection dies
                  │
                  ▼
             terminal dies
```

With tmux:

```text
Phone
  │
  └── SSH ──► tmux ──► OpenCode
                  │
                  │
             SSH disconnects
                  │
                  ▼
             OpenCode keeps running
```

This is the critical piece for reliable remote access.

---

# 4. Start OpenCode inside tmux

Instead of starting OpenCode directly:

```bash
cd ~/project
opencode
```

start a tmux session first:

```bash
tmux new -s project
```

Then:

```bash
cd ~/project
opencode
```

OpenCode is now running inside the tmux session.

You can detach from tmux without stopping OpenCode:

```text
Ctrl-B
D
```

The `Ctrl-B` is the tmux prefix. Press `Ctrl-B`, release it, then press `D`.

You should return to the normal shell.

OpenCode continues running in the background.

---

# 5. Connect from the phone

From the phone, open an SSH client and connect to the Linux laptop:

```bash
ssh <linux-user>@<tailscale-hostname>
```

Then list the tmux sessions:

```bash
tmux ls
```

For example:

```text
project-a: 1 windows
project-b: 1 windows
project-c: 1 windows
```

Attach to the project you want:

```bash
tmux attach -t project-a
```

You are now looking at the **same terminal session** where OpenCode is running.

There is no second OpenCode process.

There is no second conversation.

There is no synchronization layer.

You are controlling the original terminal.

---

# 6. Multiple OpenCode projects

This works particularly well when several projects are active simultaneously.

For example:

```bash
tmux new -s project-a
cd ~/github/project-a
opencode
```

Detach:

```text
Ctrl-B
D
```

Then create another:

```bash
tmux new -s project-b
cd ~/github/project-b
opencode
```

And another:

```bash
tmux new -s project-c
cd ~/github/project-c
opencode
```

Now:

```bash
tmux ls
```

might show:

```text
project-a
project-b
project-c
```

From the phone:

```bash
tmux attach -t project-b
```

switches directly into the OpenCode session for project B.

---

# 7. Returning to the laptop

The same session works from the laptop.

If OpenCode is running in tmux, open a terminal and run:

```bash
tmux attach -t project-a
```

You see the same session that was previously accessed from the phone.

There is no separate "mobile" or "desktop" state.

The terminal itself is persistent.

---

# 8. What happens when the phone disconnects?

Suppose OpenCode is working on a long task:

```text
OpenCode
└── Running task...
```

You close the SSH connection or lose your phone's network connection.

The tmux session remains alive.

OpenCode continues running.

Later:

```bash
ssh <linux-user>@<tailscale-hostname>
```

then:

```bash
tmux attach -t project-a
```

and the terminal is exactly where you left it.

This is one of the main reasons to use tmux.

---

# 9. Useful tmux commands

List sessions:

```bash
tmux ls
```

Create a session:

```bash
tmux new -s <name>
```

Attach to a session:

```bash
tmux attach -t <name>
```

Detach from a session:

```text
Ctrl-B
D
```

Kill a session:

```bash
tmux kill-session -t <name>
```

Rename a session:

```bash
tmux rename-session -t <old-name> <new-name>
```

---

# 10. A convenient project workflow

A simple workflow is:

```bash
tmux new -s my-project
cd ~/github/my-project
opencode
```

When leaving:

```text
Ctrl-B
D
```

From the phone:

```bash
ssh <linux-user>@<tailscale-hostname>
tmux attach -t my-project
```

This preserves the normal OpenCode project-centric workflow.

The only addition is that OpenCode is launched inside tmux.

---

# 11. Optional shell helper

A small shell function can make starting projects easier.

For example:

```bash
oc() {
    local name
    name="$(basename "$PWD")"

    if tmux has-session -t "$name" 2>/dev/null; then
        tmux attach -t "$name"
    else
        tmux new -s "$name" "opencode"
    fi
}
```

Then:

```bash
cd ~/github/my-project
oc
```

will create or attach to a tmux session named after the current directory.

This is optional. The explicit tmux commands are often easier to understand and troubleshoot.

---

# 12. Security considerations

This setup exposes SSH through the private Tailscale network, so basic SSH security still matters.

Recommended:

### Use SSH keys

Prefer public-key authentication instead of passwords.

For example:

```bash
ssh-keygen -t ed25519
```

Then install the public key on the laptop.

Once key authentication is working, password authentication can be disabled if appropriate for your environment.

### Keep Tailscale private

Do not publish:

- Tailscale IP addresses
- machine-specific Tailscale hostnames
- SSH private keys
- SSH passwords
- OpenCode passwords
- API keys
- cloud credentials
- `.env` files

Use placeholders such as:

```text
<linux-user>
<tailscale-hostname>
<project-name>
```

in public documentation.

### Do not expose SSH through the router unnecessarily

With Tailscale, the normal pattern is:

```text
Phone
  │
  │ encrypted Tailscale connection
  ▼
Laptop
  │
  └── SSH
```

rather than:

```text
Internet
  │
  ▼
Router port 22
  │
  ▼
Laptop
```

The second arrangement is unnecessary for this use case.

---

# 13. Why this is different from OpenCode's web server

There are two possible architectures.

## OpenCode server approach

```text
Phone
  │
  ▼
OpenCode web/server
  │
  ▼
OpenCode sessions
```

This can be useful when you specifically want a web-based OpenCode client.

## SSH + tmux approach

```text
Phone
  │
  ▼
SSH
  │
  ▼
tmux
  │
  ▼
existing OpenCode TUI
```

The second approach is simpler if the goal is:

> "I want to control the OpenCode that is already running on my laptop."

It does not require converting the workflow to a separate OpenCode server architecture.

---

# 14. The key concept

The important trick is not the SSH connection itself.

It is **tmux**.

SSH provides:

```text
remote terminal access
```

Tailscale provides:

```text
private network connectivity
```

tmux provides:

```text
persistent terminal sessions
```

OpenCode provides:

```text
the agent running inside that terminal
```

Together:

```text
                  Tailscale
Phone ───────────────────────────► Laptop
                                    │
                                   SSH
                                    │
                                  tmux
                                    │
                                OpenCode
                                    │
                                  Git
                                    │
                                Project
```

That gives you a lightweight remote-control system using standard Linux tools, while keeping the normal OpenCode terminal workflow intact.

---

# 15. Recommended final setup

For a personal Linux development machine, the recommended arrangement is:

```text
                    📱 Phone
                       │
                       │ Tailscale
                       ▼
                  ┌─────────┐
                  │  SSH    │
                  └────┬────┘
                       │
                       ▼
                  ┌─────────┐
                  │  tmux   │
                  └────┬────┘
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
          OpenCode  OpenCode  OpenCode
          Project A Project B Project C
```

Each project can have its own persistent OpenCode session.

You can leave the laptop running at home, disconnect your phone, come back hours later, reconnect over Tailscale, and attach to the same OpenCode session.

No public SSH port is required, and no dedicated OpenCode mobile application is required.
