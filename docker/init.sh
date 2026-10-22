#!bin/bash

printf '%s\n' 'The upstream bootstrap was removed: it fetched mutable source and hardcoded secrets.' 'Run ./start in the repository root instead.' >&2
exit 1
