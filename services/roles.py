ADMIN_ROLE = "admin"
EVENT_MANAGER_ROLE = "event_manager"
STUDENT_ROLE = "student"
TA_ROLE_PREFIX = "ta:"
FOE_DEPARTMENTS = (
    ("ARC", "Architectural Engineering (ARC)"),
    ("CVE", "Civil Engineering (CVE)"),
    ("MEC", "Mechanical Engineering (MEC)"),
    ("EEC", "Electronics and Communications Engineering (EEC)"),
    ("EEP", "Electrical Power and Machines Engineering (EEP)"),
    ("CHE", "Chemical Engineering (CHE)"),
    ("TEE", "Textile Engineering (TEE)"),
    ("NAM", "Naval Architecture and Marine Engineering (NAM)"),
    ("MIE", "Manufacturing and Industrial Engineering (MIE)"),
    ("NRE", "Nuclear and Radiation Engineering (NRE)"),
    ("CSE", "Computer and Systems Engineering (CSE)"),
    ("MSE", "Materials Science and Engineering (MSE)"),
    ("GPE", "Gas and Petrochemicals Engineering (GPE)"),
    ("EME", "Electromechanical Engineering (EME)"),
    ("CCE", "Computer and Communications Engineering (CCE)"),
    ("CAE", "Construction and Architectural Engineering (CAE)"),
    ("OCE", "Offshore and Coastal Engineering (OCE)"),
    ("BME", "Biomedical Engineering (BME)"),
    ("CEE", "Civil and Environmental Engineering (CEE)"),
    ("MRE", "Mechatronics and Robotics Engineering (MRE)"),
    ("MAE", "Mechanical and Aerospace Engineering (MAE)"),
    ("EEN", "Electronics and Nanotechnology Engineering (EEN)"),
    ("RSA", "Resilient and Smart Architecture (RSA)"),
)
TA_DEPARTMENTS = tuple(code for code, _ in FOE_DEPARTMENTS)

ROLE_CHOICES = (
    {"value": ADMIN_ROLE, "label": "Admin"},
    *(
        {"value": f"{TA_ROLE_PREFIX}{department}", "label": f"TA - {department}"}
        for department in TA_DEPARTMENTS
    ),
    {"value": EVENT_MANAGER_ROLE, "label": "Event Manager"},
    {"value": STUDENT_ROLE, "label": "Student"},
)
ROLE_VALUES = frozenset(choice["value"] for choice in ROLE_CHOICES)


def ta_department_for_role(role):
    if not isinstance(role, str) or not role.startswith(TA_ROLE_PREFIX):
        return None

    department = role.removeprefix(TA_ROLE_PREFIX)
    return department if department in TA_DEPARTMENTS else None


def can_manage_lab(role, lab_department):
    return role == ADMIN_ROLE or (
        lab_department is not None
        and ta_department_for_role(role) == lab_department
    )


def role_label(role):
    for choice in ROLE_CHOICES:
        if choice["value"] == role:
            return choice["label"]
    return role.replace("_", " ").title()
