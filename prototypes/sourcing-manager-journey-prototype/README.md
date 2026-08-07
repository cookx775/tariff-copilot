# Sourcing-manager journey prototype

> THROWAWAY PROTOTYPE — planning evidence, not production code.

Three structurally different versions of the five-minute Policy Inbox → Impact Outlook → Sourcing Review journey, switchable with `?variant=A`, `?variant=B`, or `?variant=C`.

Run from the repository root:

```sh
python3 -m http.server 4173 -d prototypes/sourcing-manager-journey-prototype
```

Then open <http://localhost:4173/?variant=A>.

All state is in memory. No operational write or external request occurs.
