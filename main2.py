import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from main_process_list import (
    add_process,
    clear_processes,
    get_all_processes,
    remove_processes_by_pid,
    replace_process,
)
from processes import FIFSscheduler, PriorityScheduler, Process, RRscheduler, SJFscheduler


class AddProcessDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        uses_priority: bool,
        show_arrival: bool = True,
        defaults: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None

        defaults = defaults or {"pid": 1, "arrival": 0, "burst": 1, "priority": 0}

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        self.pid_var = tk.IntVar(value=defaults.get("pid", 1))
        self.arrival_var = tk.IntVar(value=defaults.get("arrival", 0))
        self.burst_var = tk.IntVar(value=defaults.get("burst", 1))
        self.priority_var = tk.IntVar(value=defaults.get("priority", 0))

        ttk.Label(frame, text="PID").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(frame, from_=1, to=999999, textvariable=self.pid_var, width=12).grid(
            row=0, column=1, sticky="w", pady=4
        )

        self.arrival_label = ttk.Label(frame, text="Arrival")
        self.arrival_spin = ttk.Spinbox(frame, from_=0, to=999999, textvariable=self.arrival_var, width=12)
        self.arrival_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.arrival_spin.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Burst").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(frame, from_=1, to=999999, textvariable=self.burst_var, width=12).grid(
            row=2, column=1, sticky="w", pady=4
        )

        self.priority_label = ttk.Label(frame, text="Priority (0 is highest)")
        self.priority_spin = ttk.Spinbox(frame, from_=0, to=1024, textvariable=self.priority_var, width=12)
        self.priority_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.priority_spin.grid(row=3, column=1, sticky="w", pady=4)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="OK", command=self._accept).pack(side="right")

        if not uses_priority:
            self.priority_label.grid_remove()
            self.priority_spin.grid_remove()
        if not show_arrival:
            self.arrival_label.grid_remove()
            self.arrival_spin.grid_remove()

        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _accept(self) -> None:
        try:
            values = {
                "pid": int(self.pid_var.get()),
                "arrival": int(self.arrival_var.get()),
                "burst": int(self.burst_var.get()),
                "priority": int(self.priority_var.get()),
            }
            if values["pid"] <= 0:
                raise ValueError("PID must be greater than 0")
            if values["arrival"] < 0:
                raise ValueError("Arrival time cannot be negative")
            if values["burst"] <= 0:
                raise ValueError("Burst time must be greater than 0")
            self.result = values
            self.destroy()
        except Exception as exc:
            messagebox.showwarning("Invalid Process", str(exc), parent=self)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class MainWindowTk:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CPU Scheduler Simulator (Tkinter)")
        self.root.geometry("1400x900")

        self.scheduler_entities = {}
        self.playback_scheduler = None
        self.playback_states = []
        self.playback_index = 0
        self.playback_running = False
        self.current_time = 0
        self.playback_gantt_data = []
        self.live_process_snapshot = []
        self.timer_job = None

        self.scheduler_var = tk.StringVar(value="FCFS")
        self.quantum_var = tk.IntVar(value=2)
        self.jump_var = tk.IntVar(value=0)
        self.clock_var = tk.StringVar(value="Current Time: 0")
        self.status_var = tk.StringVar(value="Ready.")
        self.avg_waiting_var = tk.StringVar(value="0.00")
        self.avg_turnaround_var = tk.StringVar(value="0.00")

        self._build_ui()
        self.on_scheduler_type_changed()
        self.populate_processes_table()
        self.update_playback_button_labels()
        self.refresh_scheduler_entities()

    def _build_ui(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=2)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        top = ttk.LabelFrame(main, text="Scheduler", padding=8)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(top, text="Type").grid(row=0, column=0, sticky="w")
        self.scheduler_combo = ttk.Combobox(
            top,
            textvariable=self.scheduler_var,
            state="readonly",
            width=24,
            values=[
                "FCFS",
                "SJF - Non Preemptive",
                "SJF - Preemptive",
                "Priority - Non Preemptive",
                "Priority - Preemptive",
                "Round Robin",
            ],
        )
        self.scheduler_combo.grid(row=0, column=1, sticky="w", padx=(6, 14))
        self.scheduler_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_scheduler_type_changed())

        self.quantum_label = ttk.Label(top, text="Time Quantum")
        self.quantum_label.grid(row=0, column=2, sticky="w")
        self.quantum_spin = ttk.Spinbox(top, from_=1, to=1000, textvariable=self.quantum_var, width=8)
        self.quantum_spin.grid(row=0, column=3, sticky="w", padx=(6, 14))
        self.quantum_spin.bind("<FocusOut>", lambda _e: self.refresh_scheduler_entities())
        self.quantum_spin.bind("<Return>", lambda _e: self.refresh_scheduler_entities())

        ttk.Label(top, textvariable=self.clock_var, font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=4, sticky="e"
        )
        top.columnconfigure(4, weight=1)

        controls = ttk.Frame(main)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.add_btn = ttk.Button(controls, text="Add Process", command=self.on_add_process_clicked)
        self.edit_btn = ttk.Button(controls, text="Edit Selected", command=self.on_edit_selected_clicked)
        self.remove_btn = ttk.Button(controls, text="Remove Selected", command=self.on_remove_selected_clicked)
        self.clear_btn = ttk.Button(controls, text="Clear All", command=self.on_clear_all_clicked)

        self.start_btn = ttk.Button(controls, text="Start / Restart", command=self.on_start_resume_clicked)
        self.pause_btn = ttk.Button(controls, text="Pause", command=self.on_pause_clicked)
        self.run_existing_btn = ttk.Button(controls, text="Run Existing Only", command=self.on_run_existing_only_clicked)
        self.live_add_btn = ttk.Button(controls, text="Live Add Process", command=self.on_live_add_process_clicked)

        self.prev_btn = ttk.Button(controls, text="<", command=self.on_prev_time_clicked)
        self.next_btn = ttk.Button(controls, text=">", command=self.on_next_time_clicked)
        self.jump_spin = ttk.Spinbox(controls, from_=0, to=100000, textvariable=self.jump_var, width=8)
        self.jump_btn = ttk.Button(controls, text="Jump", command=self.on_move_to_time_clicked)
        self.reset_btn = ttk.Button(controls, text="Reset", command=self.on_reset_clicked)

        controls.columnconfigure(14, weight=1)

        controls_widgets = [
            self.add_btn,
            self.edit_btn,
            self.remove_btn,
            self.clear_btn,
            self.start_btn,
            self.pause_btn,
            self.run_existing_btn,
            self.live_add_btn,
            self.prev_btn,
            self.next_btn,
            self.jump_spin,
            self.jump_btn,
            self.reset_btn,
        ]
        for idx, widget in enumerate(controls_widgets):
            widget.grid(row=0, column=idx, padx=(0, 6), sticky="w")

        process_frame = ttk.LabelFrame(main, text="Processes", padding=8)
        process_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        process_frame.rowconfigure(0, weight=1)
        process_frame.columnconfigure(0, weight=1)

        self.process_table = ttk.Treeview(process_frame, columns=("pid", "arrival", "burst", "priority"), show="headings")
        self.process_table.grid(row=0, column=0, sticky="nsew")
        pscroll = ttk.Scrollbar(process_frame, orient="vertical", command=self.process_table.yview)
        pscroll.grid(row=0, column=1, sticky="ns")
        self.process_table.configure(yscrollcommand=pscroll.set)

        live_frame = ttk.LabelFrame(main, text="Live Metrics", padding=8)
        live_frame.grid(row=2, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        live_frame.rowconfigure(0, weight=1)
        live_frame.columnconfigure(0, weight=1)

        self.remaining_table = ttk.Treeview(
            live_frame,
            columns=("pid", "remaining", "waiting", "turnaround", "status"),
            show="headings",
        )
        self.remaining_table.grid(row=0, column=0, sticky="nsew")
        rscroll = ttk.Scrollbar(live_frame, orient="vertical", command=self.remaining_table.yview)
        rscroll.grid(row=0, column=1, sticky="ns")
        self.remaining_table.configure(yscrollcommand=rscroll.set)

        chart_frame = ttk.LabelFrame(main, text="Gantt Chart", padding=8)
        chart_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.columnconfigure(0, weight=1)

        self.gantt_fig = Figure(figsize=(11, 3), dpi=100)
        self.gantt_canvas = FigureCanvasTkAgg(self.gantt_fig, master=chart_frame)
        self.gantt_canvas_widget = self.gantt_canvas.get_tk_widget()
        self.gantt_canvas_widget.grid(row=0, column=0, sticky="nsew")

        bottom = ttk.Frame(main)
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(6, weight=1)

        ttk.Label(bottom, text="Average Waiting:").grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, textvariable=self.avg_waiting_var, width=8).grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(bottom, text="Average Turnaround:").grid(row=0, column=2, sticky="w")
        ttk.Label(bottom, textvariable=self.avg_turnaround_var, width=8).grid(row=0, column=3, sticky="w", padx=(4, 16))

        ttk.Label(bottom, text="Status:").grid(row=0, column=4, sticky="w")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=5, sticky="w", padx=(4, 0))

        self._configure_process_table_headers()
        self._configure_remaining_table_headers()
        self.draw_gantt_chart([])

    def _configure_process_table_headers(self) -> None:
        cols = [
            ("pid", "PID", 80),
            ("arrival", "Arrival", 100),
            ("burst", "Burst", 100),
            ("priority", "Priority", 100),
        ]
        for key, label, width in cols:
            self.process_table.heading(key, text=label)
            self.process_table.column(key, width=width, anchor="center")

    def _configure_remaining_table_headers(self) -> None:
        cols = [
            ("pid", "PID", 70),
            ("remaining", "Remaining", 90),
            ("waiting", "Waiting", 80),
            ("turnaround", "Turnaround", 90),
            ("status", "Status", 110),
        ]
        for key, label, width in cols:
            self.remaining_table.heading(key, text=label)
            self.remaining_table.column(key, width=width, anchor="center")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def uses_priority(self) -> bool:
        return self.scheduler_var.get().startswith("Priority")

    def uses_time_quantum(self) -> bool:
        return self.scheduler_var.get() == "Round Robin"

    def on_scheduler_type_changed(self) -> None:
        if self.uses_time_quantum():
            self.quantum_label.grid()
            self.quantum_spin.grid()
        else:
            self.quantum_label.grid_remove()
            self.quantum_spin.grid_remove()

        self.populate_processes_table()
        self.refresh_scheduler_entities()

    def build_scheduler_entities(self) -> dict:
        processes = get_all_processes()
        return {
            "FCFS": FIFSscheduler(processes),
            "SJF - Non Preemptive": SJFscheduler(processes, preemptive=False),
            "SJF - Preemptive": SJFscheduler(processes, preemptive=True),
            "Priority - Non Preemptive": PriorityScheduler(processes, preemptive=False),
            "Priority - Preemptive": PriorityScheduler(processes, preemptive=True),
            "Round Robin": RRscheduler(processes, int(self.quantum_var.get())),
        }

    def refresh_scheduler_entities(self) -> None:
        try:
            self.scheduler_entities = self.build_scheduler_entities()
        except Exception as exc:
            messagebox.showwarning("Scheduler", str(exc), parent=self.root)

    def get_current_scheduler_entity(self):
        return self.scheduler_entities.get(self.scheduler_var.get())

    def update_playback_button_labels(self) -> None:
        self.start_btn.configure(text="Start / Restart")
        if self.timer_job is not None:
            self.pause_btn.configure(text="Pause")
        elif self.playback_states and self.playback_index < len(self.playback_states):
            self.pause_btn.configure(text="Resume")
        else:
            self.pause_btn.configure(text="Pause")

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item_id in tree.get_children():
            tree.delete(item_id)

    def populate_processes_table(self) -> None:
        self._clear_tree(self.process_table)
        processes = sorted(get_all_processes(), key=lambda process: process.pid)

        if self.uses_priority():
            self.process_table.configure(displaycolumns=("pid", "arrival", "burst", "priority"))
            for p in processes:
                self.process_table.insert("", "end", values=(p.pid, p.arrival_time, p.burst_time, p.priority))
        else:
            self.process_table.configure(displaycolumns=("pid", "arrival", "burst"))
            for p in processes:
                self.process_table.insert("", "end", values=(p.pid, p.arrival_time, p.burst_time, ""))

    def populate_live_tables_from_state(self, state) -> None:
        self._clear_tree(self.remaining_table)
        if state is None:
            return
        for pid, row in state.iterrows():
            self.remaining_table.insert(
                "",
                "end",
                values=(
                    pid,
                    row.get("Remaining", ""),
                    row.get("Waiting", ""),
                    row.get("Turnaround", ""),
                    row.get("Status", ""),
                ),
            )

    def update_results_labels(self, avg_waiting: float, avg_turnaround: float) -> None:
        self.avg_waiting_var.set(f"{avg_waiting:.2f}")
        self.avg_turnaround_var.set(f"{avg_turnaround:.2f}")

    def update_results_from_state(self, state) -> None:
        if state is None or len(state.index) == 0:
            self.update_results_labels(0.0, 0.0)
            return

        waiting_values = []
        turnaround_values = []
        for _pid, row in state.iterrows():
            waiting = row.get("Waiting")
            turnaround = row.get("Turnaround")
            if waiting not in (None, ""):
                waiting_values.append(float(waiting))
            if turnaround not in (None, ""):
                turnaround_values.append(float(turnaround))

        avg_waiting = sum(waiting_values) / len(waiting_values) if waiting_values else 0.0
        avg_turnaround = sum(turnaround_values) / len(turnaround_values) if turnaround_values else 0.0
        self.update_results_labels(avg_waiting, avg_turnaround)

    def draw_gantt_chart(self, gantt_data: list) -> None:
        self.gantt_fig.clear()
        ax = self.gantt_fig.add_subplot(111)
        ax.set_title("Gantt Chart")

        if not gantt_data:
            ax.set_xticks([])
            ax.set_yticks([])
            self.gantt_canvas.draw()
            return

        segments = []
        current_pid = gantt_data[0][1]
        start_time = gantt_data[0][0]
        last_time = gantt_data[0][0]

        for time, pid in gantt_data[1:]:
            if pid != current_pid:
                duration = last_time - start_time + 1
                segments.append((start_time, duration, current_pid))
                current_pid = pid
                start_time = time
                last_time = time
            else:
                last_time = time
        segments.append((start_time, last_time - start_time + 1, current_pid))

        palette = []
        for cmap_name in ("tab20", "tab20b"):
            cmap = plt.colormaps.get_cmap(cmap_name)
            palette.extend([cmap(i) for i in range(cmap.N)])
        palette = palette[:32]

        def color_for_pid(pid) -> tuple:
            try:
                pid_value = int(pid)
                idx = (pid_value - 1) % len(palette) if pid_value > 0 else abs(pid_value) % len(palette)
            except Exception:
                idx = sum(ord(ch) for ch in str(pid)) % len(palette)
            return palette[idx]

        for start, duration, pid in segments:
            ax.barh(0, duration, left=start, height=0.6, color=color_for_pid(pid), edgecolor="black", label=f"P{pid}")

        boundaries = sorted({t for start, duration, _pid in segments for t in (start, start + duration)})

        ax.set_xlabel("Time")
        ax.set_ylabel("Execution Timeline")
        ax.set_yticks([0])
        ax.set_yticklabels(["CPU"])
        ax.grid(axis="x", alpha=0.3, linestyle="--")

        handles, labels = ax.get_legend_handles_labels()
        seen = set()
        unique_h = []
        unique_l = []
        for h, l in zip(handles, labels):
            if l not in seen:
                unique_h.append(h)
                unique_l.append(l)
                seen.add(l)
        if unique_h:
            ax.legend(unique_h, unique_l, loc="upper right", fontsize=9)

        ax.set_xlim(0, gantt_data[-1][0] + 1)
        if boundaries:
            ax.set_xticks(boundaries)

        self.gantt_fig.tight_layout()
        self.gantt_canvas.draw()

    def show_playback_state(self, index: int) -> None:
        if not self.playback_states:
            return

        index = max(0, min(index, len(self.playback_states)))
        self.playback_index = index
        self.current_time = index
        self.clock_var.set(f"Current Time: {self.current_time}")

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
        self.clock_var.set(f"Current Time: {self.current_time}")
        self.populate_live_tables_from_state(scheduler.states[-1])
        self.draw_gantt_chart(scheduler.gantt_chart_array)

    def _stop_timer(self) -> None:
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None

    def _schedule_tick(self) -> None:
        self.timer_job = self.root.after(1000, self.advance_playback_state)

    def advance_playback_state(self) -> None:
        self.timer_job = None

        if not self.playback_states:
            self.playback_running = False
            self.update_playback_button_labels()
            return

        if self.playback_index >= len(self.playback_states):
            self.playback_running = False
            self.show_playback_state(len(self.playback_states))
            self.update_playback_button_labels()
            self.set_status("Playback finished.")
            return

        self.show_playback_state(self.playback_index + 1)

        if self.playback_running and self.playback_index < len(self.playback_states):
            self._schedule_tick()
        else:
            self.update_playback_button_labels()

    def _prompt_process_dialog(self, title: str, show_arrival: bool, defaults: dict | None) -> dict | None:
        dialog = AddProcessDialog(
            self.root,
            title=title,
            uses_priority=self.uses_priority(),
            show_arrival=show_arrival,
            defaults=defaults,
        )
        self.root.wait_window(dialog)
        return dialog.result

    def on_add_process_clicked(self) -> None:
        all_processes = get_all_processes()
        next_pid = (max(process.pid for process in all_processes) + 1) if all_processes else 1
        values = self._prompt_process_dialog(
            title="Add Process",
            show_arrival=True,
            defaults={"pid": next_pid, "arrival": 0, "burst": 1, "priority": 0},
        )
        if values is not None:
            self.handle_add_process(values)

    def handle_add_process(self, values: dict) -> None:
        try:
            process = Process(
                pid=values["pid"],
                arrival_time=values["arrival"],
                burst_time=values["burst"],
                priority=values["priority"],
            )
            add_process(process)
            self.populate_processes_table()
            self.refresh_scheduler_entities()
            self.set_status(f"Added process P{process.pid}.")
        except Exception as exc:
            messagebox.showwarning("Invalid Process", str(exc), parent=self.root)

    def on_remove_selected_clicked(self) -> None:
        selection = self.process_table.selection()
        if not selection:
            messagebox.showwarning("Remove Process", "Please select one or more process rows to remove.", parent=self.root)
            return

        pids = []
        for item_id in selection:
            values = self.process_table.item(item_id, "values")
            if values:
                pids.append(int(values[0]))

        removed_count = remove_processes_by_pid(pids)
        self.populate_processes_table()
        self.refresh_scheduler_entities()
        if removed_count > 0:
            self.set_status(f"Removed {removed_count} selected process(es).")
        else:
            self.set_status("No processes were removed.")

    def on_edit_selected_clicked(self) -> None:
        selection = self.process_table.selection()
        if len(selection) != 1:
            messagebox.showwarning("Edit Process", "Please select exactly one process row to edit.", parent=self.root)
            return

        values = self.process_table.item(selection[0], "values")
        if not values:
            messagebox.showwarning("Edit Process", "Could not read selected process.", parent=self.root)
            return

        selected_pid = int(values[0])
        selected_process = next((p for p in get_all_processes() if p.pid == selected_pid), None)
        if selected_process is None:
            messagebox.showwarning("Edit Process", f"Process P{selected_pid} not found.", parent=self.root)
            return

        new_values = self._prompt_process_dialog(
            title="Edit Process",
            show_arrival=True,
            defaults={
                "pid": selected_process.pid,
                "arrival": selected_process.arrival_time,
                "burst": selected_process.burst_time,
                "priority": selected_process.priority,
            },
        )
        if new_values is None:
            return

        try:
            updated = Process(
                pid=new_values["pid"],
                arrival_time=new_values["arrival"],
                burst_time=new_values["burst"],
                priority=new_values["priority"],
            )
            replace_process(selected_pid, updated)
            self.populate_processes_table()
            self.refresh_scheduler_entities()
            self.set_status(f"Updated process P{selected_pid} -> P{updated.pid}.")
        except Exception as exc:
            messagebox.showwarning("Invalid Process", str(exc), parent=self.root)

    def on_clear_all_clicked(self) -> None:
        clear_processes()
        self.populate_processes_table()
        self.refresh_scheduler_entities()
        self.set_status("All processes cleared.")

    def on_start_resume_clicked(self) -> None:
        scheduler = self.get_current_scheduler_entity()
        if scheduler is None:
            messagebox.showwarning("Run Scheduler", "No scheduler entity is available.", parent=self.root)
            return

        try:
            self._stop_timer()
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
                self.show_playback_state(0)
                self._schedule_tick()
                self.update_playback_button_labels()
                self.set_status(f"Playing {self.scheduler_var.get()} live.")
            else:
                self.show_final_scheduler_state(scheduler)
                self.update_playback_button_labels()
                self.set_status(f"Ran {self.scheduler_var.get()}.")
        except Exception as exc:
            messagebox.showwarning("Run Scheduler", str(exc), parent=self.root)

    def on_pause_clicked(self) -> None:
        if self.timer_job is not None:
            self._stop_timer()
            self.playback_running = False
            self.update_playback_button_labels()
            self.set_status("Playback paused.")
        elif self.playback_states and self.playback_index < len(self.playback_states):
            self.playback_running = True
            self._schedule_tick()
            self.update_playback_button_labels()
            self.set_status("Playback resumed.")

    def on_next_time_clicked(self) -> None:
        if not self.playback_states:
            return
        self._stop_timer()
        self.playback_running = False
        self.advance_playback_state()
        self.update_playback_button_labels()
        self.set_status("Paused at next time unit.")

    def on_prev_time_clicked(self) -> None:
        if not self.playback_states:
            return
        self._stop_timer()
        self.playback_running = False
        if self.playback_index > 0:
            self.show_playback_state(self.playback_index - 1)
        self.update_playback_button_labels()
        self.set_status("Paused at previous time unit.")

    def on_move_to_time_clicked(self) -> None:
        if not self.playback_states:
            messagebox.showwarning("Jump to Time", "No playback data available. Run scheduler first.", parent=self.root)
            return

        target_time = int(self.jump_var.get())
        if target_time < 0 or target_time > len(self.playback_states):
            messagebox.showwarning(
                "Jump to Time",
                f"Time must be between 0 and {len(self.playback_states)}.",
                parent=self.root,
            )
            return

        self._stop_timer()
        self.playback_running = False
        self.show_playback_state(target_time)
        self.update_playback_button_labels()
        self.set_status(f"Jumped to time {target_time} and paused.")

    def on_run_existing_only_clicked(self) -> None:
        process_snapshot = list(get_all_processes())
        if not process_snapshot:
            messagebox.showwarning("Run Existing Only", "No processes available to run.", parent=self.root)
            return

        scheduler = self.get_current_scheduler_entity()
        if scheduler is None:
            messagebox.showwarning("Run Existing Only", "No scheduler entity is available.", parent=self.root)
            return

        self._stop_timer()
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
            self.set_status(f"Ran {self.scheduler_var.get()} on existing snapshot (non-live).")
        except Exception as exc:
            messagebox.showwarning("Run Existing Only", str(exc), parent=self.root)

    def on_live_add_process_clicked(self) -> None:
        if not self.playback_states:
            messagebox.showwarning(
                "Live Add Process",
                "Playback is not active. Start/resume the scheduler first.",
                parent=self.root,
            )
            return

        self._stop_timer()
        self.playback_running = False
        self.update_playback_button_labels()

        if not self.live_process_snapshot:
            self.live_process_snapshot = list(get_all_processes())

        next_pid = (max(p.pid for p in self.live_process_snapshot) + 1) if self.live_process_snapshot else 1
        values = self._prompt_process_dialog(
            title="Live Add Process",
            show_arrival=False,
            defaults={"pid": next_pid, "arrival": self.current_time, "burst": 1, "priority": 0},
        )

        if values is None:
            if self.playback_states and self.playback_index < len(self.playback_states):
                self.playback_running = True
                self._schedule_tick()
                self.update_playback_button_labels()
            return

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
            self.set_status(
                f"Added process P{temp_process.pid} (temporary) at time {self.current_time}. Playback resumed."
            )
        except Exception as exc:
            messagebox.showwarning("Live Add Process", str(exc), parent=self.root)
            if self.playback_states and self.playback_index < len(self.playback_states):
                self.playback_running = True
                self._schedule_tick()
                self.update_playback_button_labels()

    def re_run_scheduler_from_current_time(self, process_snapshot: list) -> None:
        scheduler = self.get_current_scheduler_entity()
        if scheduler is None:
            messagebox.showwarning("Reschedule", "No scheduler entity is available.", parent=self.root)
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
                self._schedule_tick()
            self.update_playback_button_labels()
        except Exception as exc:
            messagebox.showwarning("Reschedule", str(exc), parent=self.root)

    def on_reset_clicked(self) -> None:
        self._stop_timer()
        self.playback_scheduler = None
        self.playback_states = []
        self.playback_index = 0
        self.playback_running = False
        self.live_process_snapshot = []
        self.current_time = 0

        self.clock_var.set("Current Time: 0")
        self.jump_var.set(0)
        self.populate_live_tables_from_state(None)
        self.draw_gantt_chart([])
        self.update_results_labels(0.0, 0.0)
        self.update_playback_button_labels()
        self.set_status("Reset.")


def main() -> None:
    _ = Path(__file__).resolve().parent
    root = tk.Tk()

    # Use native ttk theme when available.
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    elif "clam" in style.theme_names():
        style.theme_use("clam")

    MainWindowTk(root)
    root.mainloop()


if __name__ == "__main__":
    main()
