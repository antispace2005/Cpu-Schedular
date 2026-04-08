# CPU Scheduler Simulator

This project is a CPU scheduling simulator with a Qt-based interface. The main source entry point is `main.py`.

## Requirements

- Python 3
- Anaconda or Miniconda
- Conda environment named `cpu_scheduler`
- Python packages used by the app: `PySide6`, `matplotlib`, `pandas`, `numpy`

## Install Environment

If you do not already have the environment, create it from the project root:

```bash
conda env create -f environment.yml
conda activate cpu_scheduler
```

If the environment already exists and you want to refresh it:

```bash
conda env update -f environment.yml --prune
```

## Run From Source

You do not need the packaged release to run the app.

### Option 1: Use the helper script

```bash
bash run.sh
```

### Option 2: Run manually in the conda environment

```bash
conda activate cpu_scheduler
python main.py
```

## Project Files

- `main.py`: Qt application entry point
- `main.ui`: main window layout
- `add_process.ui`: add/edit process dialog layout
- `processes.py`: scheduling algorithms
- `main_process_list.py`: process storage helpers
- `style.qss` and `style_light.qss`: application themes

## Notes

- The release build files are not needed for normal development or local use.
- If the app does not start, verify that the `cpu_scheduler` conda environment is active and the required packages are installed.