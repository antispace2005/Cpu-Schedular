import sys
from pathlib import Path

from PySide6.QtCore import QFile, QTimer, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
	QAbstractSpinBox,
	QApplication,
	QComboBox,
	QDialog,
	QDialogButtonBox,
	QLabel,
	QMainWindow,
	QMessageBox,
	QStyleFactory,
	QVBoxLayout,
	QPushButton,
	QSpinBox,
	QStatusBar,
	QTableWidget,
	QTableWidgetItem,
	QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from processes import FIFSscheduler, PriorityScheduler, Process, RRscheduler, SJFscheduler
from main_process_list import add_process, clear_processes, get_all_processes, replace_process, remove_processes_by_pid


APP_VERSION = "1.1"


def load_ui(ui_path: Path, parent: QWidget | None = None) -> QWidget:
	loader = QUiLoader()
	ui_file = QFile(str(ui_path))
	if not ui_file.open(QFile.ReadOnly):
		raise RuntimeError(f"Could not open UI file: {ui_path}")
	widget = loader.load(ui_file, parent)
	ui_file.close()
	if widget is None:
		raise RuntimeError(f"Could not load UI file: {ui_path}")
	return widget


class AddProcessDialog:
	def __init__(self, ui_path: Path, parent_window: QWidget | None = None):
		self.dialog = load_ui(ui_path)

		if sys.platform.startswith("linux"):
			if parent_window is not None:
				self.dialog.setParent(parent_window, Qt.WindowType.Dialog)
			self.dialog.setWindowFlag(Qt.WindowType.Dialog, True)
			self.dialog.setWindowFlag(Qt.WindowType.Window, True)
			self.dialog.setWindowFlag(Qt.WindowType.Tool, True)
			self.dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
			self.dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

		self.pidSpinBox = self.dialog.findChild(QSpinBox, "pidSpinBox")
		self.arrivalSpinBox = self.dialog.findChild(QSpinBox, "arrivalSpinBox")
		self.arrivalLabel = self.dialog.findChild(QLabel, "arrivalLabel")
		self.burstSpinBox = self.dialog.findChild(QSpinBox, "burstSpinBox")
		self.prioritySpinBox = self.dialog.findChild(QSpinBox, "prioritySpinBox")
		self.priorityLabel = self.dialog.findChild(QLabel, "priorityLabel")
		self.priorityHintLabel = self.dialog.findChild(QLabel, "priorityHintLabel")
		self.buttonBox = self.dialog.findChild(QDialogButtonBox, "buttonBox")

		self._validate_ui()
		for spinbox in (self.pidSpinBox, self.arrivalSpinBox, self.burstSpinBox, self.prioritySpinBox):
			spinbox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
		self.set_priority_visible(True)
		self.buttonBox.accepted.connect(self.dialog.accept)
		self.buttonBox.rejected.connect(self.dialog.reject)

	def _validate_ui(self) -> None:
		required = [
			self.pidSpinBox,
			self.arrivalLabel,
			self.arrivalSpinBox,
			self.burstSpinBox,
			self.prioritySpinBox,
			self.priorityLabel,
			self.priorityHintLabel,
			self.buttonBox,
		]
		if not all(required):
			raise RuntimeError("Missing one or more widgets in add_process.ui")

	def set_priority_visible(self, visible: bool) -> None:
		self.priorityLabel.setVisible(visible)
		self.prioritySpinBox.setVisible(visible)
		self.priorityHintLabel.setVisible(visible)

	def set_arrival_visible(self, visible: bool) -> None:
		self.arrivalLabel.setVisible(visible)
		self.arrivalSpinBox.setVisible(visible)

	def exec(self) -> int:
		return self.dialog.exec()

	def values(self) -> dict:
		return {
			"pid": self.pidSpinBox.value(),
			"arrival": self.arrivalSpinBox.value(),
			"burst": self.burstSpinBox.value(),
			"priority": self.prioritySpinBox.value(),
		}

	def set_values(self, pid: int, arrival: int, burst: int, priority: int) -> None:
		self.pidSpinBox.setValue(pid)
		self.arrivalSpinBox.setValue(arrival)
		self.burstSpinBox.setValue(burst)
		self.prioritySpinBox.setValue(priority)


class MainWindow:
	def __init__(self, main_ui_path: Path, add_ui_path: Path, is_dark_mode: bool):
		self.main_ui_path = main_ui_path
		self.add_ui_path = add_ui_path
		self.is_dark_mode = is_dark_mode
		self.window = load_ui(main_ui_path)
		self.window.setWindowTitle(f"CPU Scheduler Simulator v{APP_VERSION} (Qt)")
		self.scheduler_entities = {}
		self.playback_scheduler = None
		self.playback_states = []
		self.playback_index = 0
		self.playback_running = False
		self.current_time = 0
		self.playback_gantt_data = []
		self.live_process_snapshot = []
		self.timer = QTimer(self.window)
		self.timer.setInterval(1000)
		self.timer.timeout.connect(self.advance_playback_state)

		self._bind_widgets()
		self._validate_main_ui()
		self._connect_signals()
		self._initialize_view_state()
		self.refresh_scheduler_entities()

	def _bind_widgets(self) -> None:
		self.schedulerTypeComboBox = self.window.findChild(QComboBox, "schedulerTypeComboBox")
		self.timeQuantumLabel = self.window.findChild(QLabel, "timeQuantumLabel")
		self.timeQuantumSpinBox = self.window.findChild(QSpinBox, "timeQuantumSpinBox")
		self.clockLabel = self.window.findChild(QLabel, "clockLabel")

		self.processesTableWidget = self.window.findChild(QTableWidget, "processesTableWidget")
		self.remainingTableWidget = self.window.findChild(QTableWidget, "remainingTableWidget")

		self.addProcessButton = self.window.findChild(QPushButton, "addProcessButton")
		self.editProcessButton = self.window.findChild(QPushButton, "editProcessButton")
		self.removeSelectedButton = self.window.findChild(QPushButton, "removeSelectedButton")
		self.clearProcessesButton = self.window.findChild(QPushButton, "clearProcessesButton")

		self.startButton = self.window.findChild(QPushButton, "startButton")
		self.pauseButton = self.window.findChild(QPushButton, "pauseButton")
		self.runExistingOnlyButton = self.window.findChild(QPushButton, "runExistingOnlyButton")
		self.liveAddProcessButton = self.window.findChild(QPushButton, "liveAddProcessButton")
		self.prevTimeButton = self.window.findChild(QPushButton, "prevTimeButton")
		self.nextTimeButton = self.window.findChild(QPushButton, "nextTimeButton")
		self.jumpToTimeSpinBox = self.window.findChild(QSpinBox, "jumpToTimeSpinBox")
		self.jumpToTimeButton = self.window.findChild(QPushButton, "jumpToTimeButton")
		self.resetButton = self.window.findChild(QPushButton, "resetButton")

		self.avgWaitingValueLabel = self.window.findChild(QLabel, "avgWaitingValueLabel")
		self.avgTurnaroundValueLabel = self.window.findChild(QLabel, "avgTurnaroundValueLabel")
		self.statusLabel = self.window.findChild(QLabel, "statusLabel")
		self.statusbar = self.window.findChild(QStatusBar, "statusbar")
		self.chartContainer = self.window.findChild(QWidget, "chart_container")

		self._setup_gantt_chart()

	def _setup_gantt_chart(self) -> None:
		"""Initialize matplotlib figure and canvas for Gantt chart."""
		self.gantt_fig = Figure(figsize=(10, 3), dpi=100)
		self.gantt_canvas = FigureCanvas(self.gantt_fig)
		layout = QVBoxLayout(self.chartContainer)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.addWidget(self.gantt_canvas)

	def _validate_main_ui(self) -> None:
		required = [
			self.schedulerTypeComboBox,
			self.timeQuantumLabel,
			self.timeQuantumSpinBox,
			self.clockLabel,
			self.processesTableWidget,
			self.remainingTableWidget,
			self.chartContainer,
			self.addProcessButton,
			self.editProcessButton,
			self.removeSelectedButton,
			self.clearProcessesButton,
			self.startButton,
			self.pauseButton,
			self.runExistingOnlyButton,
			self.liveAddProcessButton,
			self.prevTimeButton,
			self.nextTimeButton,
			self.jumpToTimeSpinBox,
			self.jumpToTimeButton,
			self.resetButton,
			self.avgWaitingValueLabel,
			self.avgTurnaroundValueLabel,
			self.statusLabel,
		]
		if not all(required):
			raise RuntimeError("Missing one or more widgets in main.ui")

	def _connect_signals(self) -> None:
		self.schedulerTypeComboBox.currentIndexChanged.connect(self.on_scheduler_type_changed)
		self.timeQuantumSpinBox.valueChanged.connect(lambda _value: self.refresh_scheduler_entities())

		self.addProcessButton.clicked.connect(self.on_add_process_clicked)
		self.editProcessButton.clicked.connect(self.on_edit_selected_clicked)
		self.removeSelectedButton.clicked.connect(self.on_remove_selected_clicked)
		self.clearProcessesButton.clicked.connect(self.on_clear_all_clicked)

		self.startButton.clicked.connect(self.on_start_resume_clicked)
		self.pauseButton.clicked.connect(self.on_pause_clicked)
		self.runExistingOnlyButton.clicked.connect(self.on_run_existing_only_clicked)
		self.liveAddProcessButton.clicked.connect(self.on_live_add_process_clicked)
		self.prevTimeButton.clicked.connect(self.on_prev_time_clicked)
		self.nextTimeButton.clicked.connect(self.on_next_time_clicked)
		self.jumpToTimeButton.clicked.connect(self.on_move_to_time_clicked)
		self.resetButton.clicked.connect(self.on_reset_clicked)

	def _initialize_view_state(self) -> None:
		self.timeQuantumSpinBox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
		self.jumpToTimeSpinBox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
		self.jumpToTimeSpinBox.setMinimum(0)
		self.jumpToTimeSpinBox.setValue(0)
		self.startButton.setText("Start / Restart")
		self.clockLabel.setText("Current Time: 0")
		self.on_scheduler_type_changed()
		self.populate_processes_table()
		self.update_playback_button_labels()
		self.set_status("Ready.")

	def update_playback_button_labels(self) -> None:
		self.startButton.setText("Start / Restart")
		if self.timer.isActive():
			self.pauseButton.setText("Pause")
		elif self.playback_states and self.playback_index < len(self.playback_states):
			self.pauseButton.setText("Resume")
		else:
			self.pauseButton.setText("Pause")

	def show(self) -> None:
		self.window.show()

	def set_status(self, text: str) -> None:
		self.statusLabel.setText(text)
		if self.statusbar is not None:
			self.statusbar.showMessage(text, 3000)

	def uses_priority(self) -> bool:
		return self.schedulerTypeComboBox.currentText().startswith("Priority")

	def uses_time_quantum(self) -> bool:
		return self.schedulerTypeComboBox.currentText() == "Round Robin"

	def on_scheduler_type_changed(self) -> None:
		self.timeQuantumLabel.setVisible(self.uses_time_quantum())
		self.timeQuantumSpinBox.setVisible(self.uses_time_quantum())
		self.on_scheduler_mode_ui_changed()

	def on_add_process_clicked(self) -> None:
		dialog = AddProcessDialog(self.add_ui_path, self.window)
		dialog.set_priority_visible(self.uses_priority())
		all_processes = get_all_processes()
		next_pid = (max(process.pid for process in all_processes) + 1) if all_processes else 1
		dialog.set_values(
			pid=next_pid,
			arrival=0,
			burst=1,
			priority=0,
		)
		if dialog.exec() == QDialog.Accepted:
			values = dialog.values()
			self.handle_add_process(values)

	def on_remove_selected_clicked(self) -> None:
		self.handle_remove_selected_processes()

	def on_edit_selected_clicked(self) -> None:
		self.handle_edit_selected_process()

	def on_clear_all_clicked(self) -> None:
		self.handle_clear_all_processes()

	def on_start_resume_clicked(self) -> None:
		self.handle_start_or_resume()

	def on_pause_clicked(self) -> None:
		self.handle_pause()

	def on_prev_time_clicked(self) -> None:
		self.handle_prev_time()

	def on_next_time_clicked(self) -> None:
		self.handle_next_time()

	def on_move_to_time_clicked(self) -> None:
		target_time = self.jumpToTimeSpinBox.value()
		self.handle_move_to_time(target_time)

	def on_run_existing_only_clicked(self) -> None:
		self.handle_run_existing_only()

	def on_live_add_process_clicked(self) -> None:
		self.handle_live_add_process()

	def on_reset_clicked(self) -> None:
		self.handle_reset()

	def on_scheduler_mode_ui_changed(self) -> None:
		# Update table visibility when scheduler type changes
		self.populate_processes_table()

	def handle_add_process(self, values: dict) -> None:
		try:
			priority = values["priority"]
			process = Process(
				pid=values["pid"],
				arrival_time=values["arrival"],
				burst_time=values["burst"],
				priority=priority,
			)
			add_process(process)
			self.populate_processes_table()
			self.refresh_scheduler_entities()
			self.set_status(f"Added process P{process.pid}.")
		except Exception as exc:
			self.show_error("Invalid Process", str(exc))

	def handle_remove_selected_processes(self) -> None:
		selected_rows = sorted({index.row() for index in self.processesTableWidget.selectedIndexes()})
		if not selected_rows:
			self.show_error("Remove Process", "Please select one or more process rows to remove.")
			return

		selected_pids = []
		for row in selected_rows:
			pid_item = self.processesTableWidget.item(row, 0)
			if pid_item is None:
				continue
			selected_pids.append(int(pid_item.text()))

		removed_count = remove_processes_by_pid(selected_pids)
		self.populate_processes_table()
		self.refresh_scheduler_entities()
		if removed_count > 0:
			self.set_status(f"Removed {removed_count} selected process(es).")
		else:
			self.set_status("No processes were removed.")

	def handle_edit_selected_process(self) -> None:
		selected_rows = sorted({index.row() for index in self.processesTableWidget.selectedIndexes()})
		if len(selected_rows) != 1:
			self.show_error("Edit Process", "Please select exactly one process row to edit.")
			return

		row = selected_rows[0]
		pid_item = self.processesTableWidget.item(row, 0)
		if pid_item is None:
			self.show_error("Edit Process", "Could not read selected process PID.")
			return

		selected_pid = int(pid_item.text())
		selected_process = next((process for process in get_all_processes() if process.pid == selected_pid), None)
		if selected_process is None:
			self.show_error("Edit Process", f"Process P{selected_pid} not found.")
			return

		dialog = AddProcessDialog(self.add_ui_path, self.window)
		dialog.set_priority_visible(self.uses_priority())
		dialog.set_values(
			pid=selected_process.pid,
			arrival=selected_process.arrival_time,
			burst=selected_process.burst_time,
			priority=selected_process.priority,
		)

		if dialog.exec() != QDialog.Accepted:
			return

		values = dialog.values()
		try:
			priority = values["priority"]
			updated_process = Process(
				pid=values["pid"],
				arrival_time=values["arrival"],
				burst_time=values["burst"],
				priority=priority,
			)
			replace_process(selected_pid, updated_process)
			self.populate_processes_table()
			self.refresh_scheduler_entities()
			self.set_status(f"Updated process P{selected_pid} -> P{updated_process.pid}.")
		except Exception as exc:
			self.show_error("Invalid Process", str(exc))

	def handle_clear_all_processes(self) -> None:
		clear_processes()
		self.populate_processes_table()
		self.refresh_scheduler_entities()
		self.set_status("All processes cleared.")

	def build_scheduler_entities(self):
		processes = get_all_processes()
		return {
			"FCFS": FIFSscheduler(processes),
			"SJF - Non Preemptive": SJFscheduler(processes, preemptive=False),
			"SJF - Preemptive": SJFscheduler(processes, preemptive=True),
			"Priority - Non Preemptive": PriorityScheduler(processes, preemptive=False),
			"Priority - Preemptive": PriorityScheduler(processes, preemptive=True),
			"Round Robin": RRscheduler(processes, self.timeQuantumSpinBox.value()),
		}

	def refresh_scheduler_entities(self) -> None:
		self.scheduler_entities = self.build_scheduler_entities()

	def get_current_scheduler_entity(self):
		return self.scheduler_entities.get(self.schedulerTypeComboBox.currentText())

	def handle_start_or_resume(self) -> None:
		scheduler = self.get_current_scheduler_entity()
		if scheduler is None:
			self.show_error("Run Scheduler", "No scheduler entity is available.")
			return

		try:
			self.timer.stop()
			self.playback_running = False
			self.live_process_snapshot = list(get_all_processes())
			scheduler.update_list(self.live_process_snapshot)
			scheduler.schedule()
			self.playback_scheduler = scheduler
			self.playback_states = list(scheduler.states)
			self.playback_gantt_data = list(scheduler.gantt_chart_array)
			self.playback_index = 0
			self.update_results_from_state(self.playback_states[-1] if self.playback_states else None)
			if self.playback_states:
				self.playback_running = True
				self.timer.start()
				self.show_playback_state(0)
				self.update_playback_button_labels()
				self.set_status(f"Playing {self.schedulerTypeComboBox.currentText()} live.")
			else:
				self.playback_running = False
				self.timer.stop()
				self.show_final_scheduler_state(scheduler)
				self.update_playback_button_labels()
				self.set_status(f"Ran {self.schedulerTypeComboBox.currentText()}.")
		except Exception as exc:
			self.show_error("Run Scheduler", str(exc))

	def handle_pause(self) -> None:
		if self.timer.isActive():
			self.timer.stop()
			self.playback_running = False
			self.update_playback_button_labels()
			self.set_status("Playback paused.")
		elif self.playback_states and self.playback_index < len(self.playback_states):
			self.playback_running = True
			self.timer.start()
			self.update_playback_button_labels()
			self.set_status("Playback resumed.")

	def handle_next_time(self) -> None:
		"""Move forward by 1 time unit and pause."""
		if not self.playback_states:
			return
		self.timer.stop()
		self.playback_running = False
		self.advance_playback_state()
		self.update_playback_button_labels()
		self.set_status("Paused at next time unit.")

	def handle_prev_time(self) -> None:
		"""Move backward by 1 time unit and pause."""
		if not self.playback_states:
			return
		self.timer.stop()
		self.playback_running = False
		if self.playback_index > 0:
			self.show_playback_state(self.playback_index - 1)
		self.update_playback_button_labels()
		self.set_status("Paused at previous time unit.")

	def handle_move_to_time(self, target_time: int) -> None:
		"""Jump to a displayed timeline time and pause playback."""
		if not self.playback_states:
			self.show_error("Jump to Time", "No playback data available. Run scheduler first.")
			return
		
		if target_time < 0 or target_time > len(self.playback_states):
			self.show_error("Jump to Time", f"Time must be between 0 and {len(self.playback_states)}.")
			return
		
		self.timer.stop()
		self.playback_running = False
		self.show_playback_state(target_time)
		self.update_playback_button_labels()
		self.set_status(f"Jumped to time {target_time} and paused.")

	def handle_run_existing_only(self) -> None:
		process_snapshot = list(get_all_processes())
		if not process_snapshot:
			self.show_error("Run Existing Only", "No processes available to run.")
			return

		scheduler = self.get_current_scheduler_entity()
		if scheduler is None:
			self.show_error("Run Existing Only", "No scheduler entity is available.")
			return

		self.timer.stop()
		self.playback_running = False
		self.update_playback_button_labels()

		try:
			scheduler.update_list(process_snapshot)
			scheduler.schedule()
			self.playback_scheduler = scheduler
			self.playback_states = list(scheduler.states)
			self.playback_gantt_data = list(scheduler.gantt_chart_array)
			self.live_process_snapshot = []
			self.playback_index = len(self.playback_states)
			self.update_results_from_state(self.playback_states[-1] if self.playback_states else None)
			self.show_final_scheduler_state(scheduler)
			self.set_status(f"Ran {self.schedulerTypeComboBox.currentText()} on existing snapshot (non-live).")
		except Exception as exc:
			self.show_error("Run Existing Only", str(exc))

	def handle_live_add_process(self) -> None:
		"""Pause playback, add a process temporarily to the scheduler, and resume from current time."""
		if not self.playback_states:
			self.show_error("Live Add Process", "Playback is not active. Start/resume the scheduler first.")
			return

		self.timer.stop()
		self.playback_running = False
		self.update_playback_button_labels()

		if not self.live_process_snapshot:
			self.live_process_snapshot = list(get_all_processes())

		dialog = AddProcessDialog(self.add_ui_path, self.window)
		dialog.set_arrival_visible(False)
		dialog.set_priority_visible(self.uses_priority())

		next_pid = (max(process.pid for process in self.live_process_snapshot) + 1) if self.live_process_snapshot else 1
		dialog.set_values(
			pid=next_pid,
			arrival=self.current_time,
			burst=1,
			priority=0,
		)

		if dialog.exec() != QDialog.Accepted:
			if self.playback_states and self.playback_index < len(self.playback_states):
				self.playback_running = True
				self.timer.start()
				self.update_playback_button_labels()
			return

		values = dialog.values()
		try:
			live_pids = {process.pid for process in self.live_process_snapshot}
			if values["pid"] in live_pids:
				raise ValueError(f"PID {values['pid']} already exists in current live run.")

			temp_process = Process(
				pid=values["pid"],
				arrival_time=self.current_time,
				burst_time=values["burst"],
				priority=values["priority"],
			)

			process_snapshot = list(self.live_process_snapshot)
			process_snapshot.append(temp_process)
			self.live_process_snapshot = process_snapshot

			self.re_run_scheduler_from_current_time(process_snapshot)
			self.set_status(f"Added process P{temp_process.pid} (temporary) at time {self.current_time}. Playback resumed.")
		except Exception as exc:
			self.show_error("Live Add Process", str(exc))
			if self.playback_states and self.playback_index < len(self.playback_states):
				self.playback_running = True
				self.timer.start()
				self.update_playback_button_labels()

	def re_run_scheduler_from_current_time(self, process_snapshot: list) -> None:
		"""Re-run the scheduler with the modified process snapshot and resume playback from current_time."""
		scheduler = self.get_current_scheduler_entity()
		if scheduler is None:
			self.show_error("Reschedule", "No scheduler entity is available.")
			return

		try:
			scheduler.update_list(process_snapshot)
			scheduler.schedule()

			self.playback_scheduler = scheduler
			self.playback_states = list(scheduler.states)
			self.playback_gantt_data = list(scheduler.gantt_chart_array)

			if self.playback_index > len(self.playback_states):
				self.playback_index = len(self.playback_states)

			self.update_results_from_state(self.playback_states[-1] if self.playback_states else None)

			self.show_playback_state(self.playback_index)
			if self.playback_index < len(self.playback_states):
				self.playback_running = True
				self.timer.start()
			self.update_playback_button_labels()
		except Exception as exc:
			self.show_error("Reschedule", str(exc))

	def handle_reset(self) -> None:
		self.timer.stop()
		self.playback_scheduler = None
		self.playback_states = []
		self.playback_index = 0
		self.playback_running = False
		self.live_process_snapshot = []
		self.current_time = 0
		self.clockLabel.setText("Current Time: 0")
		self.jumpToTimeSpinBox.setValue(0)
		self.populate_live_tables_from_scheduler(None)
		self.draw_gantt_chart([])
		self.update_results_labels(0.0, 0.0)
		self.update_playback_button_labels()
		self.set_status("Reset.")

	def populate_processes_table(self) -> None:
		processes = sorted(get_all_processes(), key=lambda process: process.pid)
		table = self.processesTableWidget
		table.setRowCount(len(processes))
		
		if self.uses_priority():
			table.setColumnCount(4)
			table.setHorizontalHeaderLabels(["PID", "Arrival", "Burst", "Priority"])
			for row, process in enumerate(processes):
				values = [process.pid, process.arrival_time, process.burst_time, process.priority]
				for col, value in enumerate(values):
					table.setItem(row, col, QTableWidgetItem(str(value)))
		else:
			table.setColumnCount(3)
			table.setHorizontalHeaderLabels(["PID", "Arrival", "Burst"])
			for row, process in enumerate(processes):
				values = [process.pid, process.arrival_time, process.burst_time]
				for col, value in enumerate(values):
					table.setItem(row, col, QTableWidgetItem(str(value)))

		table.resizeColumnsToContents()

	def populate_remaining_table(self) -> None:
		self.populate_live_tables_from_state(None)

	def populate_live_tables_from_scheduler(self, scheduler) -> None:
		if scheduler is None:
			self.populate_live_tables_from_state(None)
			return
		if not getattr(scheduler, "states", None):
			self._fill_live_table(self.remainingTableWidget, ["PID", "Remaining", "Waiting", "Turnaround", "Status"], [])
			return
		self.populate_live_tables_from_state(scheduler.states[-1])

	def populate_live_tables_from_state(self, state) -> None:
		if state is None:
			self._fill_live_table(self.remainingTableWidget, ["PID", "Remaining", "Waiting", "Turnaround", "Status"], [])
			return

		self._fill_live_table(
			self.remainingTableWidget,
			["PID", "Remaining", "Waiting", "Turnaround", "Status"],
			[
				(
					pid,
					row.get("Remaining", ""),
					row.get("Waiting", ""),
					row.get("Turnaround", ""),
					row.get("Status", ""),
				)
				for pid, row in state.iterrows()
			],
		)

	def show_playback_state(self, index: int) -> None:
		if not self.playback_states:
			return
		index = max(0, min(index, len(self.playback_states)))
		self.playback_index = index
		self.current_time = index
		self.clockLabel.setText(f"Current Time: {self.current_time}")
		current_state = self.playback_states[index - 1] if index > 0 else None
		self.populate_live_tables_from_state(current_state)
		gantt_data_up_to_now = [entry for entry in self.playback_gantt_data if entry[0] < index]
		self.draw_gantt_chart(gantt_data_up_to_now)

	def show_final_scheduler_state(self, scheduler) -> None:
		if scheduler is None or not getattr(scheduler, "states", None):
			self.populate_live_tables_from_state(None)
			self.draw_gantt_chart([])
			return
		self.current_time = len(scheduler.states)
		self.clockLabel.setText(f"Current Time: {self.current_time}")
		self.populate_live_tables_from_state(scheduler.states[-1])
		self.draw_gantt_chart(scheduler.gantt_chart_array)

	def advance_playback_state(self) -> None:
		if not self.playback_states:
			self.timer.stop()
			self.playback_running = False
			self.update_playback_button_labels()
			return

		if self.playback_index >= len(self.playback_states):
			self.timer.stop()
			self.playback_running = False
			self.show_playback_state(len(self.playback_states))
			self.update_playback_button_labels()
			self.set_status("Playback finished.")
			return

		self.show_playback_state(self.playback_index + 1)

	def _fill_live_table(self, table: QTableWidget, headers: list[str], rows: list[tuple]) -> None:
		table.setRowCount(len(rows))
		table.setColumnCount(len(headers))
		table.setHorizontalHeaderLabels(headers)
		for row_index, row_values in enumerate(rows):
			for col_index, value in enumerate(row_values):
				table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
		table.resizeColumnsToContents()

	def draw_gantt_chart(self, gantt_data: list) -> None:
		"""Draw a 1D Gantt chart as a single timeline with colored segments for each process."""
		self.gantt_fig.clear()
		fig_bg = "#1e1f22" if self.is_dark_mode else "#f4f6f8"
		text_color = "#e6e6e6" if self.is_dark_mode else "#1f2328"
		grid_color = "#3a3d41" if self.is_dark_mode else "#d0d7de"
		self.gantt_fig.patch.set_facecolor(fig_bg)

		if not gantt_data:
			ax = self.gantt_fig.add_subplot(111)
			ax.set_facecolor(fig_bg)
			ax.set_title("Gantt Chart", color=text_color)
			ax.tick_params(colors=text_color)
			for spine in ax.spines.values():
				spine.set_color(grid_color)
			ax.set_xticks([])
			ax.set_yticks([])
			self.gantt_canvas.draw()
			return

		ax = self.gantt_fig.add_subplot(111)
		ax.set_facecolor(fig_bg)
		
		# Group consecutive same PID entries into (start_time, duration, pid)
		segments = []
		if gantt_data:
			current_pid = gantt_data[0][1]
			start_time = gantt_data[0][0]
			last_time_for_current_pid = gantt_data[0][0]

			for time, pid in gantt_data[1:]:
				if pid != current_pid:
					# End the segment for current_pid at the last time we saw it
					duration = last_time_for_current_pid - start_time + 1
					segments.append((start_time, duration, current_pid))
					
					# Start new segment
					current_pid = pid
					start_time = time
					last_time_for_current_pid = time
				else:
					# Same pid, update the last time we saw it
					last_time_for_current_pid = time

			# Final segment
			duration = last_time_for_current_pid - start_time + 1
			segments.append((start_time, duration, current_pid))

		# Stable PID->color mapping: deterministic 32-color cycle.
		# This prevents existing process colors from changing when new PIDs are added.
		palette = []
		for cmap_name in ("tab20", "tab20b"):
			cmap = plt.colormaps.get_cmap(cmap_name)
			palette.extend([cmap(i) for i in range(cmap.N)])
		palette = palette[:32]

		def color_for_pid(pid) -> tuple:
			try:
				pid_value = int(pid)
				index = (pid_value - 1) % len(palette) if pid_value > 0 else abs(pid_value) % len(palette)
			except (TypeError, ValueError):
				# Fallback deterministic index for any non-integer PID representation.
				index = sum(ord(ch) for ch in str(pid)) % len(palette)
			return palette[index]

		# Draw segments on a single y-axis (y=0)
		y_position = 0
		for start_time, duration, pid in segments:
			ax.barh(y_position, duration, left=start_time, height=0.6, 
					align="center", color=color_for_pid(pid), edgecolor='black', linewidth=1, label=f"P{pid}")

		# Show only segment boundary times on the x-axis (start/end of each run).
		boundary_times = sorted({t for start_time, duration, _pid in segments for t in (start_time, start_time + duration)})

		# Format the plot
		ax.set_xlabel("Time", fontsize=12, color=text_color)
		ax.set_ylabel("Execution Timeline", fontsize=12, color=text_color)
		ax.set_title("Gantt Chart", fontsize=14, color=text_color)
		ax.set_yticks([0])
		ax.set_yticklabels(["CPU"])
		ax.tick_params(colors=text_color)
		ax.grid(axis="x", color=grid_color, alpha=0.35, linestyle="--")
		for spine in ax.spines.values():
			spine.set_color(grid_color)
		
		# Add legend with unique PIDs only
		handles, labels = ax.get_legend_handles_labels()
		seen_labels = set()
		unique_handles_labels = []
		for handle, label in zip(handles, labels):
			if label not in seen_labels:
				unique_handles_labels.append((handle, label))
				seen_labels.add(label)
		
		if unique_handles_labels:
			ax.legend([h for h, _ in unique_handles_labels], [l for _, l in unique_handles_labels], 
					 loc='upper right', fontsize=10, facecolor=fig_bg, edgecolor=grid_color, labelcolor=text_color)
		
		if gantt_data:
			last_time = gantt_data[-1][0] + 1
			ax.set_xlim(0, last_time)
		if boundary_times:
			ax.set_xticks(boundary_times)
			ax.set_xticklabels([str(time_value) for time_value in boundary_times])
		
		self.gantt_fig.tight_layout()
		self.gantt_canvas.draw()

	def update_results_labels(self, avg_waiting: float, avg_turnaround: float) -> None:
		self.avgWaitingValueLabel.setText(f"{avg_waiting:.2f}")
		self.avgTurnaroundValueLabel.setText(f"{avg_turnaround:.2f}")

	def update_results_from_state(self, state) -> None:
		if state is None or len(state.index) == 0:
			self.update_results_labels(0.0, 0.0)
			return

		waiting_values = []
		turnaround_values = []
		for _pid, row in state.iterrows():
			waiting = row.get("Waiting", None)
			turnaround = row.get("Turnaround", None)
			if waiting is not None and waiting != "":
				waiting_values.append(float(waiting))
			if turnaround is not None and turnaround != "":
				turnaround_values.append(float(turnaround))

		avg_waiting = sum(waiting_values) / len(waiting_values) if waiting_values else 0.0
		avg_turnaround = sum(turnaround_values) / len(turnaround_values) if turnaround_values else 0.0
		self.update_results_labels(avg_waiting, avg_turnaround)

	def draw_gantt(self) -> None:
		pass

	def show_error(self, title: str, message: str) -> None:
		QMessageBox.warning(self.window, title, message)


def main() -> None:
	app = QApplication(sys.argv)
	app.setStyle(QStyleFactory.create("Fusion"))

	base_dir = Path(__file__).resolve().parent
	main_ui_path = base_dir / "main.ui"
	add_ui_path = base_dir / "add_process.ui"
	dark_style_path = base_dir / "style.qss"
	light_style_path = base_dir / "style_light.qss"

	is_dark_mode = False
	try:
		is_dark_mode = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
	except Exception:
		is_dark_mode = app.palette().window().color().value() < 128

	selected_style_path = dark_style_path if is_dark_mode else light_style_path
	if selected_style_path.exists():
		app.setStyleSheet(selected_style_path.read_text(encoding="utf-8"))
	elif dark_style_path.exists():
		app.setStyleSheet(dark_style_path.read_text(encoding="utf-8"))

	main_window = MainWindow(main_ui_path, add_ui_path, is_dark_mode)
	main_window.show()

	sys.exit(app.exec())


if __name__ == "__main__":
	main()
