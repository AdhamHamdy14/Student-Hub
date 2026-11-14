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
the username or password (for example, `@` as `%40`).

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

The current Supabase tables were created separately. Compare the database schema
with the models before applying any generated initial migration to that database.
