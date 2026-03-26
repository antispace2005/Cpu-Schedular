from processes import *

Processes = [
    Process(pid=1, arrival_time=0, burst_time=10, priority=3),
    Process(pid=2, arrival_time=2, burst_time=4, priority=3),
    Process(pid=3, arrival_time=4, burst_time=8, priority=2),
    Process(pid=4, arrival_time=6, burst_time=6, priority=1),
    Process(pid=5, arrival_time=8, burst_time=1, priority=1),
    Process(pid=6, arrival_time=10, burst_time=12, priority=3),
    Process(pid=7, arrival_time=1, burst_time=5, priority=0)]

scheduler = PriorityScheduler(Processes, preemptive=False)


# \\scheduler.schedule()



scheduler = FIFSscheduler(Processes)
# scheduler.schedule()
scheduler = SJFscheduler(Processes, preemptive=True)
scheduler.schedule()
