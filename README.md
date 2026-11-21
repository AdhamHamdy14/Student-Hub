# Student Hub

## Run locally

From the project directory, create and activate a virtual environment, then install
the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Set `DATABASE_URL` in the ignored `.env` file to your Supabase PostgreSQL
connection string before starting the app. URL-encode reserved characters in
the username or password (for example, `@` as `%40`). Also set `SECRET_KEY` to
a strong random value; generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `.env` as `SECRET_KEY=<generated-value>`. Keep it
private and stable across deployments; changing it signs out existing sessions.

For password-reset emails, set `MAIL_EMAIL` to a Gmail or Outlook sender account
and `MAIL_APP_PASSWORD` to that account's app password. Gmail addresses use
Gmail SMTP and Outlook, Hotmail, Live, and MSN addresses use Outlook SMTP.
Both providers use STARTTLS, and SMTP AUTH must be enabled for the sender account.

Microsoft sign-in and student sign-up use Microsoft Entra ID. Register a Web
application and add `http://127.0.0.1:5000/login/microsoft/callback` as a
redirect URI (use the corresponding HTTPS URL in production). Set
`MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` in `.env`, and set
`MICROSOFT_EMAIL_DOMAIN` to the university email domain (defaults to
`alexu.edu.eg`). `MICROSOFT_TENANT_ID` defaults to `organizations`; you can set
it to the university tenant ID to limit the Microsoft sign-in authority.
Optionally set `MICROSOFT_REDIRECT_URI` when the automatically generated
callback URL does not match the registered URI. New users complete a profile
with their department and optional University ID and are assigned the student
role.

Authenticated sessions use a per-login token, allow only one active device per
account (a new login invalidates the previous device), and expire after one
hour without a request. Five incorrect passwords for an account trigger a
15-minute login lockout. Passwords are stored as Werkzeug password hashes, not
plaintext. Password-reset OTPs are sent by email, expire after 15 minutes, and
are stored hashed.

Admins can create accounts and assign any supported role from the Manage Roles
page. New passwords follow the reset-password rule: at least 8 characters with
at least one number or symbol. TA accounts inherit their department from the
selected TA role; other new accounts start with an unassigned department.

Open these pages to preview the app:

- Home: http://127.0.0.1:5000/
- Events: http://127.0.0.1:5000/events
- Event details: http://127.0.0.1:5000/events/embedded-systems-bootcamp
- Registration confirmation: http://127.0.0.1:5000/events/embedded-systems-bootcamp/registered

## Database migrations

Create a migration after changing the models, review the generated revision,
then apply it:

```powershell
flask --app app db migrate -m "Describe the schema change"
flask --app app db upgrade
```

The initial migration creates the full schema, including the login-lockout
columns. Run it against a new, empty database with `flask --app app db upgrade`.
For an existing database, compare its schema with the models and establish a
baseline before applying this initial migration. Werkzeug password hashing and
login lockout do not require additional secret keys.
