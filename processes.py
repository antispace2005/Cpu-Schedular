import pandas as pd
import copy

class Process:
    def __init__(self, pid, arrival_time, burst_time, priority):
        #Priority is 0 for highest and 1024 for lowest

        if pid is None:
            raise ValueError("PID cannot be None")

        self.pid = pid
        self.arrival_time = arrival_time
        self.burst_time = burst_time
        self.priority = priority
        
        # Tracking variables for scheduling algorithms
        self.remaining_time = burst_time  # Crucial for preemptive algorithms (like Round Robin)
        self.completion_time = 0
        self.turnaround_time = 0
        self.waiting_time = 0
        self.response_time = -1           # -1 indicates the process hasn't been executed yet

    def __repr__(self):
        """Makes printing the process object readable."""
        return (f"Process(PID={self.pid}, Arrival={self.arrival_time}, "
                f"Burst={self.burst_time}, Priority={self.priority})")


class Scheduler:
    """Base class for all scheduling algorithms."""
    def __init__(self, processes):
        # 1. Sort the processes based on PID
        # (Assuming PIDs are all comparable, e.g., all integers)
        self.processes = sorted(copy.deepcopy(processes), key=lambda p: p.pid,reverse=True)
        
        # 2. Initialize the empty table variable
        self.process_table = None
        
        # 3. Build the initial Pandas table
        self.update_table()

    def add_processes(self, processes):
        """Add one process or many processes to the scheduler."""
        if processes is None:
            return

        if isinstance(processes, Process):
            processes = [processes]

        new_processes = copy.deepcopy(list(processes))
        self.processes.extend(new_processes)
        self.processes = sorted(self.processes, key=lambda p: p.pid, reverse=True)
        self.update_table()

    def update_list(self, processes):
        """Replace the entire process list with a new list of processes."""
        if processes is None:
            raise ValueError("Process list cannot be None")

        self.processes = sorted(copy.deepcopy(list(processes)), key=lambda p: p.pid, reverse=True)
        self.update_table()

    def remove_process(self, pid):
        """Remove a process by PID."""
        initial_len = len(self.processes)
        self.processes = [p for p in self.processes if p.pid != pid]

        if len(self.processes) == initial_len:
            raise ValueError(f"Process with PID {pid} not found")

        self.update_table()

    def edit_process(self, pid, arrival_time=None, burst_time=None, priority=None):
        """Edit process fields by PID."""
        process = next((p for p in self.processes if p.pid == pid), None)
        if process is None:
            raise ValueError(f"Process with PID {pid} not found")

        if arrival_time is not None:
            process.arrival_time = arrival_time

        if burst_time is not None:
            process.burst_time = burst_time
            process.remaining_time = burst_time

        if priority is not None:
            process.priority = priority

        self.update_table()

    def update_table(self):
        """
        Pulls the current attributes from the Process objects and 
        generates/updates the Pandas DataFrame.
        """
        # Create a list of dictionaries mapping the attributes
        pids = set(p.pid for p in self.processes)
        if len(pids) != len(self.processes):
            raise ValueError("Duplicate PIDs found. Each process must have a unique PID.")
            
        data = [{
            "PID": p.pid,
            "Arrival": p.arrival_time,
            "Burst": p.burst_time,
            "Priority": p.priority,
            "Remaining": p.remaining_time,
            "Completion": p.completion_time,
            "Turnaround": p.turnaround_time,
            "Waiting": p.waiting_time,
            "Response": p.response_time
        } for p in self.processes]
        self.states = []
        self.gantt_chart_array = []

        
        # Create the DataFrame
        self.process_table = pd.DataFrame(data)

        # Set the PID as the index so you can easily look up rows by ID
        # e.g., self.process_table.loc[1] gets you Process 1's data
        if not self.process_table.empty:
            self.process_table.set_index("PID", inplace=True)

    def display_table(self):
        """Helper to print the table neatly."""
        print(self.process_table)

    import pandas as pd

    def generate_state(self, running_process, ready_queue, not_arrived_processes, finished_processes, current_time=None):
        """
        Builds the state DataFrame by directly extracting processes from their current queues.
        No dependency on self.processes!
        """
        categorized_processes = []
        
        # 1. Grab the running process
        if running_process:
            categorized_processes.append((running_process, "Running"))
            
        # 2. Grab the not arrived processes
        for p in not_arrived_processes:
            status = "Not Arrived"
            if current_time is not None and p.arrival_time <= current_time:
                status = "Ready"
            categorized_processes.append((p, status))
            
        # 3. Grab the ready processes (flattening the priority queues)
        for sublist in ready_queue:
            for p in sublist:
                categorized_processes.append((p, "Ready"))
                
        # 4. Grab the finished processes
        for p in finished_processes:
            categorized_processes.append((p, "Finished"))
            
        # 5. Build the data table
        data = []
        for p, status in categorized_processes:
            data.append({
                "PID": p.pid,
                "Arrival": p.arrival_time,
                "Burst": p.burst_time,
                "Priority": p.priority,
                "Remaining": p.remaining_time,
                "Completion": p.completion_time,
                "Turnaround": p.turnaround_time,
                "Waiting": p.waiting_time,
                "Response": p.response_time,
                "Status": status 
            })
            
        # Optional: Sort by PID so your table rows don't jump around every tick
        data.sort(key=lambda x: x["PID"])

        return pd.DataFrame(data).set_index("PID")

class PriorityScheduler(Scheduler):
    """Implements the Priority Scheduling algorithm."""
    def __init__(self, processes, preemptive=False):
        super().__init__(processes)

        self.preemptive = preemptive
        # You can add any additional initialization here if needed


                    


    def schedule(self):

        time=0
        running_process = None
        finished_processes = []
        not_arrived_processes = copy.deepcopy(self.processes) # Sort by arrival time for easy access


        # Assuming 'tasks' is your list of objects
        maximum = max(obj.priority for obj in not_arrived_processes)

        # Create a list of empty lists (entries = maximum + 1 to include the max index)
        ready_queue = [[] for _ in range(maximum + 1)]


        while len(finished_processes) < len(self.processes):
            for i in range(len(not_arrived_processes) - 1, -1, -1):
                process = not_arrived_processes[i]
                if time >= process.arrival_time:

                    # Remove from not_arrived and add to ready_queue
                    ready_queue[process.priority].append(not_arrived_processes.pop(i))
                    ready_queue[process.priority][-1].response_time = 0





            if running_process is None:
                # Find the highest priority non-empty queue
                for priority_level in range(len(ready_queue)):
                    if ready_queue[priority_level]:  # If there's a process in this priority level
                        running_process = ready_queue[priority_level].pop(0)  # Get the first process
                        break


            if running_process:
                running_process.remaining_time -= 1
                self.gantt_chart_array.append((time, running_process.pid))
                # print(f"Time {time}: Running Process {running_process.pid} (Remaining Time: {running_process.remaining_time})")

                if running_process.response_time == 0:
                    running_process.response_time = time - running_process.arrival_time

                if running_process.remaining_time == 0:
                    running_process.completion_time = time + 1
                    running_process.turnaround_time = running_process.completion_time - running_process.arrival_time
                    running_process.waiting_time = running_process.turnaround_time - running_process.burst_time
                    finished_processes.append(running_process)
                    running_process = None
                elif self.preemptive:
                    if hasattr(self, 'update_priority'):
                        self.update_priority(running_process)
                    ready_queue[running_process.priority].insert(0, running_process)
                    running_process = None

            self.states.append(self.generate_state(running_process, ready_queue, not_arrived_processes, finished_processes, current_time=time + 1))
            time += 1





















class FIFSscheduler(PriorityScheduler):
    """Implements the First-In-First-Out Scheduling algorithm."""
    def __init__(self, processes):
        temp = copy.deepcopy(processes)
        for p in temp:
            p.priority = p.arrival_time
        super().__init__(temp,preemptive=False)
        # You can add any additional initialization here if needed

    def add_processes(self, processes):
        if processes is None:
            return

        if isinstance(processes, Process):
            processes = [processes]

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = p.arrival_time
        super().add_processes(new_processes)

    def update_list(self, processes):
        if processes is None:
            raise ValueError("Process list cannot be None")

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = p.arrival_time
        super().update_list(new_processes)

    def edit_process(self, pid, arrival_time=None, burst_time=None, priority=None):
        _ = priority
        super().edit_process(pid, arrival_time=arrival_time, burst_time=burst_time, priority=None)
        process = next((p for p in self.processes if p.pid == pid), None)
        process.priority = process.arrival_time
        self.update_table()




class SJFscheduler(PriorityScheduler):
    """Implements the Shortest Job First Scheduling algorithm."""
    def __init__(self, processes, preemptive=False):
        temp = copy.deepcopy(processes)
        for p in temp:
            p.priority = p.burst_time
        super().__init__(temp, preemptive=preemptive)

    def update_priority(self, running_process):
        running_process.priority = running_process.remaining_time

    def add_processes(self, processes):
        if processes is None:
            return

        if isinstance(processes, Process):
            processes = [processes]

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = p.burst_time
        super().add_processes(new_processes)

    def update_list(self, processes):
        if processes is None:
            raise ValueError("Process list cannot be None")

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = p.burst_time
        super().update_list(new_processes)

    def edit_process(self, pid, arrival_time=None, burst_time=None, priority=None):
        _ = priority
        super().edit_process(pid, arrival_time=arrival_time, burst_time=burst_time, priority=None)
        process = next((p for p in self.processes if p.pid == pid), None)
        process.priority = process.burst_time
        self.update_table()



class RRscheduler(Scheduler):
    """Implements the Round Robin Scheduling algorithm."""
    def __init__(self, processes, time_quantum):
        temp = copy.deepcopy(processes)
        for p in temp:
            p.priority = 0  # All processes have the same priority in Round Robin
        super().__init__(temp)
        self.time_quantum = time_quantum

    def add_processes(self, processes):
        if processes is None:
            return

        if isinstance(processes, Process):
            processes = [processes]

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = 0
        super().add_processes(new_processes)

    def update_list(self, processes):
        if processes is None:
            raise ValueError("Process list cannot be None")

        new_processes = copy.deepcopy(list(processes))
        for p in new_processes:
            p.priority = 0
        super().update_list(new_processes)

    def edit_process(self, pid, arrival_time=None, burst_time=None, priority=None):
        _ = priority
        super().edit_process(pid, arrival_time=arrival_time, burst_time=burst_time, priority=None)
        process = next((p for p in self.processes if p.pid == pid), None)
        process.priority = 0
        self.update_table()


    def schedule(self):
        counter=0
        time=0
        running_process = None
        finished_processes = []
        not_arrived_processes = copy.deepcopy(self.processes) # Sort by arrival time for easy access


        ready_queue = [[]]


        while len(finished_processes) < len(self.processes):
            # print(f"Time {time}: Checking for arriving processes...")
            for i in range(len(not_arrived_processes) - 1, -1, -1):
                process = not_arrived_processes[i]
                if time >= process.arrival_time:

                    # Remove from not_arrived and add to ready_queue
                    ready_queue[0].append(not_arrived_processes.pop(i))
                    ready_queue[0][-1].response_time = 0
            # print(f"Ready Queue: {[p.pid for p in ready_queue[0]]}")

            if running_process is None:
                if ready_queue[0]:  # If there's a process in the ready queue
                    running_process = ready_queue[0].pop(0)  # Get the first process
            
            # print(f"Running Process: {running_process.pid if running_process else 'None'}")

            if running_process:
                running_process.remaining_time -= 1
                counter+=1
                self.gantt_chart_array.append((time, running_process.pid))
                # print(f"Time {time}: Running Process {running_process.pid} (Remaining Time: {running_process.remaining_time})")

                if running_process.response_time == 0:
                    running_process.response_time = time - running_process.arrival_time

                if running_process.remaining_time == 0:
                    running_process.completion_time = time + 1
                    running_process.turnaround_time = running_process.completion_time - running_process.arrival_time
                    running_process.waiting_time = running_process.turnaround_time - running_process.burst_time
                    finished_processes.append(running_process)
                    running_process = None
                    counter=0

                elif counter == self.time_quantum:
                    ready_queue[0].append(running_process)
                    running_process = None
                    counter=0

            self.states.append(self.generate_state(running_process, ready_queue, not_arrived_processes, finished_processes, current_time=time + 1))
            time += 1


