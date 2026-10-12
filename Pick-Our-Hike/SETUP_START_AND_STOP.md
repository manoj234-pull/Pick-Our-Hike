# Setup, startup and shutdown

## First-time setup on Windows

1. Download the complete repository ZIP and extract it. Open the folder containing
   `app.py`, `pyproject.toml`, `src`, `assets`, and `data`. Do not run from inside the ZIP.
2. Install [Python 3.12](https://www.python.org/downloads/) and
   [Ollama](https://ollama.com/download). Open the Ollama desktop app.
   Reopen VS Code/PowerShell after installation so PATH changes take effect.
3. Open PowerShell in the extracted project folder. Run these commands separately:

```powershell
py -3.12 --version
ollama --version
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
ollama pull phi4-mini
ollama list
```

The final dot in `install -e .` means this project. The model download requires
several GB of disk space and may take time. Review Ollama's download progress;
Ctrl+C cancels it. The application does not download anything automatically.
Do not copy another person's virtual environment or Python runtime.

4. Start the app:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

5. Open http://127.0.0.1:8501. Keep this terminal open. Enter a request with date,
departure/return times, hikers and their limits. Dogs are optional. Answer follow-up
questions in the same chat. Review **Trip details** and **Results**, then **View hike**.
There is no booking or external registration action.

## Returning later

Open Ollama, open a terminal in the project folder, and run the Streamlit command
above. Packages and models do not need reinstalling on every startup.

## macOS/Linux

With Python 3.12 and Ollama installed, the equivalent commands are:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
ollama pull phi4-mini
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

The current project was checked on Windows; these equivalent commands have not
been tested on macOS/Linux in this workspace.

## Optional configuration

Defaults: model `phi4-mini`, Ollama at `http://127.0.0.1:11434`.
For a different already-installed model, set this before starting Streamlit:

```powershell
$env:PICK_OUR_HIKE_MODEL = 'your-installed-model-name'
```

A different model can change behavior. No API key is needed for the default local setup.

## Troubleshooting

| Problem | Action |
|---|---|
| `ollama` is not recognized | Reopen VS Code and the terminal after installation. |
| Cannot connect to Ollama | Open Ollama; verify `ollama list` works. |
| Model not installed | Run `ollama pull phi4-mini` and wait for completion. |
| `pick_our_hike` or `streamlit` missing | Run the pip installation command from the project root. |
| Connection refused in browser | Start Streamlit and keep its terminal running. |
| Port 8501 occupied | Use `--server.port 8502`, then open http://127.0.0.1:8502. |
| Data or artwork missing | Extract the full project, including `data` and `assets`. |
| Saved details look wrong | Correct them in the chat or start a new trip; interpretation is not perfect. |

## Optional notebook debugging

The app does not require Jupyter. To use the included debugger, install the kernel:

```powershell
.venv\Scripts\python.exe -m pip install ipykernel
```

In VS Code, use Microsoft's Python and Jupyter extensions. Open
`output/jupyter-notebook/debug_agent_conversation.ipynb` as a notebook, select the
project's `.venv` kernel, and run the cells. `RUN_LIVE=False` avoids model calls.
Set it to `True` only for a real diagnostic request. Clear outputs before sharing
or committing the notebook; they can contain conversation details.

## Shutdown

1. Press **Ctrl+C** in the Streamlit terminal.
2. Interrupt running notebook cells, then shut down/disconnect its kernel.
3. Unload the model if desired:

```powershell
ollama stop phi4-mini
```

4. To stop Ollama completely, choose **Quit Ollama** in its system-tray menu.
   If you started `ollama serve` in a terminal, press Ctrl+C there instead.
5. Close browser tabs and VS Code. You do not need to uninstall or delete the model.

Conversation state is not stored in a database. Restarting the app may clear it.
