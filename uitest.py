import sys
import copy
from collections import deque
from pathlib import Path

from PySide6.QtCore import QFile, QTimer
from PySide6.QtCore import Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from processes import Process, FIFSscheduler, PriorityScheduler, RRscheduler, SJFscheduler


class SchedulerApp:
    def __init__(self, main_ui_path, add_process_ui_path):
        self.loader = QUiLoader()
        self.main_ui_path = main_ui_path
        self.add_process_ui_path = add_process_ui_path

        self.window = self._load_ui(main_ui_path)
        self.window.setWindowTitle("CPU Scheduler Simulator")

        self.schedulerTypeComboBox = self.window.findChild(QComboBox, "schedulerTypeComboBox")
        self.timeQuantumLabel = self.window.findChild(QLabel, "timeQuantumLabel")
        self.timeQuantumSpinBox = self.window.findChild(QSpinBox, "timeQuantumSpinBox")
        self.liveSchedulingCheckBox = self.window.findChild(QCheckBox, "liveSchedulingCheckBox")
        self.clockLabel = self.window.findChild(QLabel, "clockLabel")
        self.addProcessButton = self.window.findChild(QPushButton, "addProcessButton")
        self.removeSelectedButton = self.window.findChild(QPushButton, "removeSelectedButton")
        self.clearProcessesButton = self.window.findChild(QPushButton, "clearProcessesButton")
        self.processesTableWidget = self.window.findChild(QTableWidget, "processesTableWidget")
        self.remainingTableWidget = self.window.findChild(QTableWidget, "remainingTableWidget")
        self.avgWaitingValueLabel = self.window.findChild(QLabel, "avgWaitingValueLabel")
        self.avgTurnaroundValueLabel = self.window.findChild(QLabel, "avgTurnaroundValueLabel")
        self.startButton = self.window.findChild(QPushButton, "startButton")
        self.pauseButton = self.window.findChild(QPushButton, "pauseButton")
        self.stepButton = self.window.findChild(QPushButton, "stepButton")
        self.jumpToTimeSpinBox = self.window.findChild(QSpinBox, "jumpToTimeSpinBox")
        self.jumpToTimeButton = self.window.findChild(QPushButton, "jumpToTimeButton")
        self.runExistingOnlyButton = self.window.findChild(QPushButton, "runExistingOnlyButton")
        self.resetButton = self.window.findChild(QPushButton, "resetButton")
        self.statusLabel = self.window.findChild(QLabel, "statusLabel")
        self.statusbar = self.window.findChild(QStatusBar, "statusbar")

        if not all([
            self.schedulerTypeComboBox,
            self.timeQuantumLabel,
            self.timeQuantumSpinBox,
            self.liveSchedulingCheckBox,
            self.clockLabel,
            self.addProcessButton,
            self.removeSelectedButton,
            self.clearProcessesButton,
            self.processesTableWidget,
            self.remainingTableWidget,
            self.avgWaitingValueLabel,
            self.avgTurnaroundValueLabel,
            self.startButton,
            self.pauseButton,
            self.stepButton,
            self.jumpToTimeSpinBox,
            self.jumpToTimeButton,
            self.runExistingOnlyButton,
            self.resetButton,
            self.statusLabel,
        ]):
            raise RuntimeError("Failed to load one or more UI widgets from main.ui")

        self.chart_container = self.window.findChild(QWidget, "chart_container")
        if self.chart_container is None:
            raise RuntimeError("Failed to load chart_container from main.ui")

        self.layout = QVBoxLayout(self.chart_container)
        self.fig = Figure(figsize=(8, 2))
        self.canvas = FigureCanvas(self.fig)
        self.layout.addWidget(self.canvas)

        self.ax = self.fig.add_subplot(111)
        self.bars = []
        self.hovered_bar = None
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_hover)

        self.process_templates = []
        self.processes = []
        self.finished_processes = []
        self.playback_engine = None
        self.playback_states = []
        self.playback_gantt = []
        self.playback_index = 0
        self.current_process = None
        self.current_time = 0
        self.running_segment = None
        self.segments = []
        self.rr_queue = deque()
        self.rr_enqueued = set()
        self.rr_quantum_counter = 0
        self.sequence_counter = 0
        self.timer = QTimer(self.window)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.advance_one_time_unit)

        self.addProcessButton.clicked.connect(self.open_add_process_dialog)
        self.removeSelectedButton.clicked.connect(self.remove_selected_process)
        self.clearProcessesButton.clicked.connect(self.clear_all_processes)
        self.startButton.clicked.connect(self.start_or_resume)
        self.pauseButton.clicked.connect(self.pause)
        self.stepButton.clicked.connect(self.step_once)
        self.jumpToTimeButton.clicked.connect(self.jump_to_time)
        self.runExistingOnlyButton.clicked.connect(self.run_existing_only)
        self.resetButton.clicked.connect(self.reset_simulation)
        self.schedulerTypeComboBox.currentIndexChanged.connect(self.update_scheduler_controls)

        self.update_scheduler_controls()
        self.refresh_all_views()

    def _load_ui(self, path):
        ui_file = QFile(path)
        ui_file.open(QFile.ReadOnly)
        widget = self.loader.load(ui_file)
        ui_file.close()
        return widget

    def current_mode(self):
        return self.schedulerTypeComboBox.currentText()

    def scheduler_class_for_mode(self):
        mode = self.current_mode()
        if mode == "FCFS":
            return FIFSscheduler
        if mode == "SJF - Non Preemptive":
            return lambda processes: SJFscheduler(processes, preemptive=False)
        if mode == "SJF - Preemptive":
            return lambda processes: SJFscheduler(processes, preemptive=True)
        if mode == "Priority - Non Preemptive":
            return lambda processes: PriorityScheduler(processes, preemptive=False)
        if mode == "Priority - Preemptive":
            return lambda processes: PriorityScheduler(processes, preemptive=True)
        if mode == "Round Robin":
            return lambda processes: RRscheduler(processes, self.timeQuantumSpinBox.value())
        return FIFSscheduler

    def uses_priority_input(self):
        return self.current_mode().startswith("Priority")

    def uses_time_quantum(self):
        return self.current_mode() == "Round Robin"

    def update_scheduler_controls(self):
        use_priority = self.uses_priority_input()
        use_quantum = self.uses_time_quantum()

        self.timeQuantumLabel.setVisible(use_quantum)
        self.timeQuantumSpinBox.setVisible(use_quantum)

        # Keep the dialog fields aligned with the selected scheduler type.
        self._pending_priority_visible = use_priority

    def build_process_from_dialog(self, dialog):
        pid = dialog.pidSpinBox.value()
        arrival = dialog.arrivalSpinBox.value()
        burst = dialog.burstSpinBox.value()
        priority = dialog.prioritySpinBox.value() if self.uses_priority_input() else 0
        return Process(pid, arrival, burst, priority)

    def _set_process_sequence(self, process):
        setattr(process, "_sequence", self.sequence_counter)
        self.sequence_counter += 1

    def register_process(self, process):
        if any(p.pid == process.pid for p in self.processes):
            raise ValueError(f"Process with PID {process.pid} already exists.")

        self._set_process_sequence(process)
        self.processes.append(process)
        self.process_templates.append({
            "pid": process.pid,
            "arrival_time": process.arrival_time,
            "burst_time": process.burst_time,
            "priority": process.priority,
            "sequence": process._sequence,
        })
        self.refresh_all_views()

    def open_add_process_dialog(self):
        dialog = self._load_ui(self.add_process_ui_path)

        # Force a true dialog window so tiling compositors like Hyprland float it.
        dialog.setParent(self.window, Qt.WindowType.Dialog)
        dialog.setWindowFlag(Qt.WindowType.Dialog, True)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setWindowFlag(Qt.WindowType.Tool, True)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        priority_label = dialog.findChild(QLabel, "priorityLabel")
        priority_spin = dialog.findChild(QSpinBox, "prioritySpinBox")
        hint_label = dialog.findChild(QLabel, "priorityHintLabel")
        if priority_label is not None:
            priority_label.setVisible(self.uses_priority_input())
        if priority_spin is not None:
            priority_spin.setVisible(self.uses_priority_input())
        if hint_label is not None:
            hint_label.setVisible(self.uses_priority_input())

        button_box = dialog.findChild(QDialogButtonBox, "buttonBox")
        if button_box is not None:
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            try:
                process = self.build_process_from_dialog(dialog)
                self.register_process(process)
                self.set_status(f"Added process P{process.pid}.")
            except Exception as exc:
                QMessageBox.warning(self.window, "Invalid Process", str(exc))

    def remove_selected_process(self):
        selected_rows = sorted({index.row() for index in self.processesTableWidget.selectedIndexes()}, reverse=True)
        if not selected_rows:
            self.set_status("Select a process row first.")
            return

        removed_any = False
        for row in selected_rows:
            pid_item = self.processesTableWidget.item(row, 0)
            if pid_item is None:
                continue
            pid = int(pid_item.text())
            self.processes = [p for p in self.processes if p.pid != pid]
            self.process_templates = [p for p in self.process_templates if p["pid"] != pid]
            removed_any = True

        if removed_any:
            self.refresh_all_views()
            self.set_status("Selected process removed.")

    def clear_all_processes(self):
        self.pause()
        self.process_templates.clear()
        self.processes.clear()
        self.finished_processes.clear()
        self.current_process = None
        self.current_time = 0
        self.running_segment = None
        self.segments.clear()
        self.rr_queue.clear()
        self.rr_enqueued.clear()
        self.rr_quantum_counter = 0
        self.refresh_all_views()
        self.set_status("All processes cleared.")

    def set_status(self, text):
        self.statusLabel.setText(text)
        if self.statusbar is not None:
            self.statusbar.showMessage(text, 3000)

    def update_process_table(self):
        table = self.processesTableWidget
        table.setRowCount(len(self.processes))
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["PID", "Arrival", "Burst", "Priority"])

        for row, process in enumerate(sorted(self.processes, key=lambda p: (p.arrival_time, getattr(p, "_sequence", 0), p.pid))):
            values = [process.pid, process.arrival_time, process.burst_time, process.priority]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))

        table.resizeColumnsToContents()

    def update_remaining_table(self):
        table = self.remainingTableWidget
        table.setRowCount(len(self.processes))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["PID", "Remaining", "Status"])

        for row, process in enumerate(sorted(self.processes, key=lambda p: (p.pid, getattr(p, "_sequence", 0)))):
            status = "Finished" if process.remaining_time <= 0 else (
                "Running" if self.current_process and process.pid == self.current_process.pid else "Ready"
            )
            values = [process.pid, process.remaining_time, status]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))

        table.resizeColumnsToContents()

    def update_results(self):
        finished = [p for p in self.processes if p.remaining_time <= 0 and p.completion_time > 0]
        if not finished:
            self.avgWaitingValueLabel.setText("0.00")
            self.avgTurnaroundValueLabel.setText("0.00")
            return

        avg_wait = sum(p.waiting_time for p in finished) / len(finished)
        avg_tat = sum(p.turnaround_time for p in finished) / len(finished)
        self.avgWaitingValueLabel.setText(f"{avg_wait:.2f}")
        self.avgTurnaroundValueLabel.setText(f"{avg_tat:.2f}")

    def sync_from_scheduler_engine(self, engine):
        self.processes = copy.deepcopy(engine.processes)
        self.finished_processes = [p for p in self.processes if p.remaining_time <= 0]
        self.current_process = None
        self.segments = []
        if getattr(engine, "gantt_chart_array", None):
            compressed = []
            for time, pid in engine.gantt_chart_array:
                label = f"P{pid}" if pid is not None else "IDLE"
                color = self.color_for_pid(pid) if pid is not None else "#D3D3D3"
                if not compressed or compressed[-1]["label"] != label:
                    compressed.append({"label": label, "start": time, "end": time + 1, "color": color})
                else:
                    compressed[-1]["end"] = time + 1
            self.segments = compressed

        self.current_time = self.segments[-1]["end"] if self.segments else 0

        self.refresh_all_views()

    def build_engine(self):
        processes = [Process(item["pid"], item["arrival_time"], item["burst_time"], item["priority"]) for item in self.process_templates]
        for process, template in zip(processes, self.process_templates):
            process._sequence = template["sequence"]

        factory = self.scheduler_class_for_mode()
        return factory(processes)

    def prepare_playback(self):
        engine = self.build_engine()
        engine.schedule()
        self.playback_engine = engine
        self.playback_states = list(engine.states)
        self.playback_gantt = list(engine.gantt_chart_array)
        self.playback_index = 0

        # Keep the final computed values available for summary statistics.
        self.processes = copy.deepcopy(engine.processes)
        self.finished_processes = [p for p in self.processes if p.remaining_time <= 0]
        self.update_results()

    def reset_playback_view(self):
        self.playback_index = 0
        self.current_time = 0
        self.current_process = None
        self.segments = []
        self.redraw_gantt_chart()
        self.clockLabel.setText("Current Time: 0")

    def update_remaining_table_from_state(self, state_df):
        table = self.remainingTableWidget
        table.setRowCount(len(state_df))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["PID", "Remaining", "Status"])

        for row, pid in enumerate(state_df.index):
            row_data = state_df.loc[pid]
            table.setItem(row, 0, QTableWidgetItem(str(pid)))
            table.setItem(row, 1, QTableWidgetItem(str(row_data["Remaining"])))
            table.setItem(row, 2, QTableWidgetItem(str(row_data["Status"])))

        table.resizeColumnsToContents()

    def redraw_gantt_from_playback(self):
        self.ax.clear()
        self.bars.clear()

        if not self.playback_gantt or self.playback_index <= 0:
            self.ax.set_xlabel("Time (seconds)")
            self.ax.set_title("CPU Scheduler Gantt Chart")
            self.ax.set_yticks([])
            self.ax.spines["top"].set_visible(False)
            self.ax.spines["right"].set_visible(False)
            self.canvas.draw_idle()
            return

        current_events = self.playback_gantt[:self.playback_index]
        segments = []
        for time, pid in current_events:
            label = f"P{pid}" if pid is not None else "IDLE"
            color = self.color_for_pid(pid) if pid is not None else "#D3D3D3"
            if not segments or segments[-1]["label"] != label:
                segments.append({"label": label, "start": time, "end": time + 1, "color": color})
            else:
                segments[-1]["end"] = time + 1

        for segment in segments:
            color = segment["color"]
            start = segment["start"]
            width = segment["end"] - segment["start"]
            bar_container = self.ax.barh(y="CPU", width=width, left=start, color=color, edgecolor="black", linewidth=1)
            rect = bar_container[0]
            label = segment["label"]

            self.bars.append({
                "rect": rect,
                "orig_color": color,
                "name": label,
                "start": start,
                "duration": width,
            })
            self.ax.text(start + width / 2, "CPU", label, ha="center", va="center", color="black", fontweight="bold")

        self.ax.set_xlabel("Time (seconds)")
        self.ax.set_title("CPU Scheduler Gantt Chart")
        ticks = sorted({0, *[segment["start"] for segment in segments], *[segment["end"] for segment in segments]})
        self.ax.set_xticks(ticks)
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.canvas.draw_idle()

    def render_playback_state(self):
        state = None
        if self.playback_index > 0 and self.playback_states:
            state_idx = min(self.playback_index - 1, len(self.playback_states) - 1)
            state = self.playback_states[state_idx]

        self.update_process_table()
        if state is not None:
            self.update_remaining_table_from_state(state)
        else:
            self.update_remaining_table()

        self.update_results()
        self.redraw_gantt_from_playback()
        self.clockLabel.setText(f"Current Time: {self.playback_index}")

    def advance_playback_frame(self):
        if not self.playback_states:
            self.set_status("No scheduler playback is ready.")
            return

        if self.playback_index >= len(self.playback_states):
            self.timer.stop()
            self.set_status("Playback finished.")
            return

        self.playback_index += 1
        self.current_time = self.playback_index
        self.render_playback_state()

        if self.playback_index >= len(self.playback_states):
            self.timer.stop()
            self.set_status("Playback finished.")

    def refresh_all_views(self):
        self.update_process_table()
        self.update_remaining_table()
        self.update_results()
        self.redraw_gantt_chart()
        self.clockLabel.setText(f"Current Time: {self.current_time}")

    def color_for_pid(self, pid):
        palette = [
            "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
            "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC", "#8E6C8A",
        ]
        return palette[pid % len(palette)] if isinstance(pid, int) else "#BBBBBB"

    def redraw_gantt_chart(self):
        self.ax.clear()
        self.bars.clear()

        if not self.segments:
            self.ax.set_xlabel("Time (seconds)")
            self.ax.set_title("CPU Scheduler Gantt Chart")
            self.ax.set_yticks([])
            self.ax.spines["top"].set_visible(False)
            self.ax.spines["right"].set_visible(False)
            self.canvas.draw_idle()
            return

        for segment in self.segments:
            color = segment["color"]
            start = segment["start"]
            width = segment["end"] - segment["start"]
            bar_container = self.ax.barh(y="CPU", width=width, left=start, color=color, edgecolor="black", linewidth=1)
            rect = bar_container[0]
            label = segment["label"]

            self.bars.append({
                "rect": rect,
                "orig_color": color,
                "name": label,
                "start": start,
                "duration": width,
            })
            self.ax.text(start + width / 2, "CPU", label, ha="center", va="center", color="black", fontweight="bold")

        self.ax.set_xlabel("Time (seconds)")
        self.ax.set_title("CPU Scheduler Gantt Chart")
        ticks = sorted({0, *[segment["start"] for segment in self.segments], *[segment["end"] for segment in self.segments]})
        self.ax.set_xticks(ticks)
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.canvas.draw_idle()

    def on_mouse_hover(self, event):
        if event.inaxes != self.ax:
            return

        found_bar = None
        for bar_data in self.bars:
            contains, _ = bar_data["rect"].contains(event)
            if contains:
                found_bar = bar_data
                break

        if found_bar != self.hovered_bar:
            if self.hovered_bar:
                self.hovered_bar["rect"].set_edgecolor("black")
                self.hovered_bar["rect"].set_linewidth(1)
                self.hovered_bar["rect"].set_alpha(1.0)
                QToolTip.hideText()

            self.hovered_bar = found_bar

            if self.hovered_bar:
                self.hovered_bar["rect"].set_edgecolor("red")
                self.hovered_bar["rect"].set_linewidth(3)
                self.hovered_bar["rect"].set_alpha(0.75)
                if event.guiEvent:
                    pos = event.guiEvent.globalPosition().toPoint()
                    tooltip_text = (
                        f"<b>Process:</b> {self.hovered_bar['name']}<br>"
                        f"<b>Start:</b> {self.hovered_bar['start']}<br>"
                        f"<b>Duration:</b> {self.hovered_bar['duration']}"
                    )
                    QToolTip.showText(pos, tooltip_text)

            self.canvas.draw_idle()

    def pause(self):
        self.timer.stop()
        self.set_status("Paused.")

    def start_or_resume(self):
        if not self.processes:
            QMessageBox.information(self.window, "No Processes", "Add at least one process first.")
            return

        if self.liveSchedulingCheckBox.isChecked():
            if not self.playback_states:
                self.prepare_playback()
                self.reset_playback_view()
            elif self.playback_index == 0:
                self.render_playback_state()

            if not self.timer.isActive():
                self.timer.start()
                self.set_status("Live scheduling started.")
        else:
            self.run_existing_only()

    def step_once(self):
        if not self.processes:
            return
        was_running = self.timer.isActive()
        if was_running:
            self.timer.stop()
        if not self.playback_states:
            self.prepare_playback()
            self.reset_playback_view()
        self.advance_playback_frame()
        if was_running:
            self.timer.start()

    def jump_to_time(self):
        target = self.jumpToTimeSpinBox.value()
        if target < 0:
            return

        was_running = self.timer.isActive()
        self.timer.stop()

        if not self.playback_states:
            self.prepare_playback()

        self.playback_index = max(0, min(target, len(self.playback_states)))
        self.current_time = self.playback_index
        self.render_playback_state()
        self.set_status(f"Moved to time {target}.")

        if was_running and not self.is_done() and self.liveSchedulingCheckBox.isChecked():
            self.timer.start()

    def reset_simulation(self):
        was_running = self.timer.isActive()
        self.timer.stop()

        templates = copy.deepcopy(self.process_templates)
        self.processes = [Process(item["pid"], item["arrival_time"], item["burst_time"], item["priority"]) for item in templates]
        for process, item in zip(self.processes, templates):
            process._sequence = item["sequence"]

        self.finished_processes = []
        self.current_process = None
        self.current_time = 0
        self.running_segment = None
        self.segments = []
        self.playback_engine = None
        self.playback_states = []
        self.playback_gantt = []
        self.playback_index = 0
        self.rr_queue.clear()
        self.rr_enqueued.clear()
        self.rr_quantum_counter = 0
        self.refresh_all_views()
        self.set_status("Simulation reset.")

        if was_running and self.liveSchedulingCheckBox.isChecked():
            self.timer.start()

    def run_existing_only(self):
        if not self.processes:
            QMessageBox.information(self.window, "No Processes", "Add at least one process first.")
            return

        self.pause()
        engine = self.build_engine()
        engine.schedule()

        self.sync_from_scheduler_engine(engine)
        self.set_status("Finished non-live execution.")

    def is_done(self):
        return all(process.remaining_time <= 0 for process in self.processes)

    def active_processes(self):
        return [p for p in self.processes if p.arrival_time <= self.current_time and p.remaining_time > 0]

    def _choose_candidate_non_rr(self):
        eligible = [p for p in self.processes if p.arrival_time <= self.current_time and p.remaining_time > 0]
        if not eligible:
            return None

        mode = self.current_mode()
        if mode == "FCFS":
            return min(eligible, key=lambda p: (p.arrival_time, getattr(p, "_sequence", 0), p.pid))
        if mode == "SJF - Non Preemptive":
            if self.current_process and self.current_process.remaining_time > 0:
                return self.current_process
            return min(eligible, key=lambda p: (p.burst_time, p.arrival_time, getattr(p, "_sequence", 0), p.pid))
        if mode == "SJF - Preemptive":
            return min(eligible, key=lambda p: (p.remaining_time, p.arrival_time, getattr(p, "_sequence", 0), p.pid))
        if mode == "Priority - Non Preemptive":
            if self.current_process and self.current_process.remaining_time > 0:
                return self.current_process
            return min(eligible, key=lambda p: (p.priority, p.arrival_time, getattr(p, "_sequence", 0), p.pid))
        if mode == "Priority - Preemptive":
            return min(eligible, key=lambda p: (p.priority, p.arrival_time, getattr(p, "_sequence", 0), p.pid))
        return None

    def _sync_rr_queue(self):
        for process in self.processes:
            if process.arrival_time <= self.current_time and process.remaining_time > 0:
                if process is not self.current_process and process.pid not in self.rr_enqueued:
                    self.rr_queue.append(process)
                    self.rr_enqueued.add(process.pid)

    def _start_segment(self, process):
        label = f"P{process.pid}" if process is not None else "IDLE"
        color = self.color_for_pid(process.pid) if process is not None else "#D3D3D3"

        if self.segments and self.segments[-1]["label"] == label:
            self.segments[-1]["end"] += 1
        else:
            self.segments.append({
                "label": label,
                "start": self.current_time,
                "end": self.current_time + 1,
                "color": color,
            })

    def _finalize_completed(self, process):
        if process.completion_time == 0:
            process.completion_time = self.current_time + 1
            process.turnaround_time = process.completion_time - process.arrival_time
            process.waiting_time = process.turnaround_time - process.burst_time
            if process.response_time == -1:
                process.response_time = self.current_time - process.arrival_time
            self.finished_processes.append(process)

    def advance_one_time_unit(self, redraw=True):
        if not self.playback_states:
            self.prepare_playback()
            self.reset_playback_view()

        self.advance_playback_frame()
        if redraw:
            self.canvas.draw_idle()

    def show(self):
        self.window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    qss_path = Path(__file__).with_name("style.qss")
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    scheduler = SchedulerApp("main.ui", "add_process.ui")
    scheduler.show()
    sys.exit(app.exec())