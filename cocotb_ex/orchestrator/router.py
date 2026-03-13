from dataclasses import dataclass


@dataclass
class CaseState:
    logic_failures: int = 0
    total_attempts: int = 0


class Router:
    def __init__(self, config: dict):
        self.config = config or {}
        self.job_role_map = self.config.get("job_role_map", {})
        self.stickiness = self.config.get("stickiness", {})
        self.escalation = self.config.get("escalation", {})

    def role_for_job(self, job_type: str, default_role: str | None = None) -> str | None:
        return self.job_role_map.get(job_type, default_role)

    def _in_place_classes(self) -> set[str]:
        return set(self.stickiness.get("in_place_fix_classes", []) or [])

    def should_increment_logic(self, error_class: str) -> bool:
        if error_class != "LOGIC":
            return False
        if error_class in self._in_place_classes() and self.stickiness.get("in_place_fix_behavior", {}).get(
            "do_not_increment_logic_failures", False
        ):
            return False
        return True

    def update_state(self, error_class: str, state: CaseState) -> None:
        state.total_attempts += 1
        if self.should_increment_logic(error_class):
            state.logic_failures += 1

    def should_escalate(
        self,
        error_class: str,
        state: CaseState,
        tb3_touched: bool = False,
        blast_radius_files: int | None = None,
        blast_radius_loc: int | None = None,
    ) -> bool:
        force = self.escalation.get("force_escalate_when", {})
        if tb3_touched and force.get("tb3_touched"):
            return True
        if blast_radius_files is not None and blast_radius_files >= force.get("blast_radius_files_ge", 1 << 30):
            return True
        if blast_radius_loc is not None and blast_radius_loc >= force.get("blast_radius_loc_ge", 1 << 30):
            return True

        threshold = self.escalation.get("logic_error_threshold", 0)
        if error_class == "LOGIC" and threshold and state.logic_failures >= threshold:
            return True

        max_attempts = self.escalation.get("max_total_attempts_per_case", 0)
        if max_attempts and state.total_attempts >= max_attempts:
            return True
        return False

    def next_role(self, job_type: str, error_class: str, current_role: str | None) -> str | None:
        if error_class in self._in_place_classes():
            return current_role
        return self.role_for_job(job_type, current_role)

    def escalation_role(self) -> str | None:
        return self.escalation.get("escalation_target_role")
