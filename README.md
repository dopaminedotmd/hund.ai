# hund

> An agent engine in your terminal. Bring your own key, connect to any provider.

hund is a terminal agent that connects to the API you choose and works alongside you in the machine.

hund has one task: understand you and your environment as well as possible, so it can give the most precise, personal help it can.

## How hund gets better

hund watches how you work. From that usage it writes its own skills, learns your motives, and sharpens those skills to become as effective a helper for you as possible.

You can watch it happen. Every domain hund works in has an ASCII leveling bar that fills in as the ability grows:

```
CLR ████████░░  Adept      PRC ██████░░░░  Apprentice
EFF █████████░  Expert     END ████░░░░░░  Novice
```

Real feedback from real work, shown in the terminal.

## Install

```powershell
git clone https://github.com/dopaminedotmd/hund.ai
cd hund.ai
uv sync --extra dev
setx HUND_API_KEY "sk-..."      # your key, any provider
.venv\Scripts\hund.exe
```

## Use

```
hund           # start the REPL
hund doctor    # read the machine
hund stats     # see the leveling bars
hund skills    # list skills
```

In the REPL: /help, /stats, /skills, /skills vault, /skills equip <name>, /skills park <name>, /skills swap <old> <new>, /tools, /doctor, /usage, /compress, /theme, /export, /exit.

## License

Apache-2.0.
