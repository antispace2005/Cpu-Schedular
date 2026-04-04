from processes import Process


main_process_list: list[Process] = []


def pid_exists(pid: int) -> bool:
    return any(process.pid == pid for process in main_process_list)


def add_process(process: Process) -> None:
    if pid_exists(process.pid):
        raise ValueError(f"Process with PID {process.pid} already exists.")
    main_process_list.append(process)


def get_all_processes() -> list[Process]:
    return list(main_process_list)


def clear_processes() -> None:
    main_process_list.clear()


def replace_process(old_pid: int, new_process: Process) -> None:
    old_index = next((i for i, process in enumerate(main_process_list) if process.pid == old_pid), None)
    if old_index is None:
        raise ValueError(f"Process with PID {old_pid} not found.")

    if new_process.pid != old_pid and pid_exists(new_process.pid):
        raise ValueError(f"Process with PID {new_process.pid} already exists.")

    main_process_list[old_index] = new_process
