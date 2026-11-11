
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the same folder as this Python file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

JIRA_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

# Validate configuration
if not all([JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, PROJECT_KEY]):
    raise ValueError("Missing Jira configuration. Check your .env file.")

JIRA_URL = JIRA_URL.rstrip("/")


def connect_to_jira():
    url = f"{JIRA_URL}/rest/api/3/myself"

    response = requests.get(
        url,
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Accept": "application/json"},
        timeout=30
    )

    if response.status_code != 200:
        print("Jira connection failed!")
        print("Status:", response.status_code)
        print("Error:", response.text[:500])
        return False

    user = response.json()

    print("Jira connection successful!")
    print("Authenticated user:", user.get("displayName"))

    return True


def get_project():
    url = f"{JIRA_URL}/rest/api/3/project/{PROJECT_KEY}"

    response = requests.get(
        url,
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Accept": "application/json"},
        timeout=30
    )

    if response.status_code == 200:
        project = response.json()

        print("\nProject details")
        print("----------------------")
        print("Project Name:", project["name"])
        print("Project Key:", project["key"])
        print("Project ID:", project["id"])
    else:
        print("Unable to retrieve project.")
        print("Status:", response.status_code)
        print(response.text[:500])


if __name__ == "__main__":
    if connect_to_jira():
        get_project()
