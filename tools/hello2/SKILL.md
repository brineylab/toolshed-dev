---
name: hello2
description: A copy of hello: prints the OS, the user, and the GPU it sees. Built by a flyloft campaign in tier two.
metadata:
  version: 1.0.1
---
# hello2

Image: `ghcr.io/brineylab/toolshed-dev/hello2:1.0.1`

## Commands

`hello` prints `os=<id>`, `user=<uid>`, and `gpu=<name or none>`.

## Inputs and outputs

None; three lines on stdout.

## Running it

`podman run --rm ghcr.io/brineylab/toolshed-dev/hello2:1.0.1 hello`
