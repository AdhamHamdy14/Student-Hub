import os
import time
import unittest
from datetime import date, time as time_of_day, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from werkzeug.security import check_password_hash, generate_password_hash

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ["DATABASE_URL"] = "sqlite://"

from app import app
from models import (
    Event,
    Lab,
    LabSlot,
    PasswordReset,
    Profile,
    StarredEvent,
    db,
    utc_now,
)
from services.password_reset_email import (
    GMAIL_SMTP_PORT,
    GMAIL_SMTP_SERVER,
    OUTLOOK_SMTP_PORT,
    OUTLOOK_SMTP_SERVER,
    send_password_reset_email,
)


class AuthenticationSessionTests(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key",
            MAIL_EMAIL="student-hub@outlook.com",
            MAIL_APP_PASSWORD="test-mail-app-password",
        )
        with app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add(
                Profile(
                    id=1,
                    name="Test Student",
                    primary_email="student@example.com",
                    password_hash=generate_password_hash("password123"),
                    department="Testing",
                )
            )
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    @staticmethod
    def login(client, password="password123", email="student@example.com"):
        return client.post(
            "/login",
            data={"email": email, "password": password},
        )

    def test_password_is_stored_as_a_hash(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertNotEqual(profile.password_hash, "password123")
            self.assertTrue(check_password_hash(profile.password_hash, "password123"))

    def test_login_page_offers_outlook_and_student_signup_creates_student_account(self):
        client = app.test_client()
        login_page = client.get("/login")
        self.assertIn(b"Continue with Outlook", login_page.data)

        with client.session_transaction() as auth_session:
            auth_session["microsoft_signup"] = {
                "email": "new.student@alexu.edu.eg",
                "name": "New Student",
            }

        signup_page = client.get("/signup/microsoft")
        self.assertEqual(signup_page.status_code, 200)
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = client.post(
            "/signup/microsoft",
            data={
                "_csrf_token": csrf,
                "department": "CSE",
                "student_id": "S12345",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/home")

        with app.app_context():
            user = Profile.query.filter_by(
                primary_email="new.student@alexu.edu.eg"
            ).one()
            self.assertEqual(user.name, "New Student")
            self.assertEqual(user.department, "CSE")
            self.assertEqual(user.student_id, "S12345")
            self.assertEqual(user.role, "student")

    def test_microsoft_callback_rejects_accounts_outside_allowed_domain(self):
        client = app.test_client()
        microsoft_client = Mock()
        microsoft_client.authorize_access_token.return_value = {
            "userinfo": {
                "email": "person@example.com",
                "preferred_username": "person@other.edu",
                "name": "University Student",
            }
        }

        with patch.dict(
            app.config,
            {
                "MICROSOFT_CLIENT_ID": "test-client-id",
                "MICROSOFT_CLIENT_SECRET": "test-client-secret",
                "MICROSOFT_EMAIL_DOMAIN": "alexu.edu.eg",
            },
        ), patch(
            "routes.auth_pages.microsoft_oauth.create_client",
            return_value=microsoft_client,
        ):
            response = client.get("/login/microsoft/callback")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/login")
        with client.session_transaction() as auth_session:
            self.assertNotIn("microsoft_signup", auth_session)

    def test_microsoft_callback_signs_in_existing_university_account(self):
        with app.app_context():
            user = db.session.get(Profile, 1)
            user.primary_email = "existing.student@alexu.edu.eg"
            db.session.commit()

        client = app.test_client()
        microsoft_client = Mock()
        microsoft_client.authorize_access_token.return_value = {
            "userinfo": {
                "email": "existing.student@alexu.edu.eg",
                "name": "Existing Student",
            }
        }

        with patch.dict(
            app.config,
            {
                "MICROSOFT_CLIENT_ID": "test-client-id",
                "MICROSOFT_CLIENT_SECRET": "test-client-secret",
                "MICROSOFT_EMAIL_DOMAIN": "alexu.edu.eg",
            },
        ), patch(
            "routes.auth_pages.microsoft_oauth.create_client",
            return_value=microsoft_client,
        ):
            response = client.get("/login/microsoft/callback")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/home")
        with client.session_transaction() as auth_session:
            self.assertEqual(auth_session["profile_id"], 1)
            self.assertTrue(auth_session["auth_token"])

    def test_second_login_invalidates_the_previous_device(self):
        first_device = app.test_client()
        second_device = app.test_client()

        self.login(first_device)
        with first_device.session_transaction() as auth_session:
            first_token = auth_session["auth_token"]
            self.assertTrue(auth_session.permanent)

        self.login(second_device)
        with second_device.session_transaction() as auth_session:
            second_token = auth_session["auth_token"]
            self.assertNotEqual(first_token, second_token)

        response = first_device.get("/events", follow_redirects=True)
        self.assertIn(b"Your session is no longer active", response.data)

    def test_inactive_session_expires_and_revokes_its_token(self):
        client = app.test_client()
        self.login(client)

        with client.session_transaction() as auth_session:
            auth_session["auth_last_activity"] = time.time() - 3601

        response = client.get("/home", follow_redirects=True)
        self.assertIn(b"one hour of inactivity", response.data)

        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertIsNone(profile.tokens)

    def test_static_assets_do_not_query_the_authenticated_user(self):
        client = app.test_client()
        self.login(client)

        with patch.object(
            db.session,
            "get",
            side_effect=AssertionError("Static requests should not query profiles."),
        ):
            response = client.get("/static/app/css/labs-admin.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"body.labs-admin", response.data)
        response.close()

    def test_mobile_navigation_links_to_profile_page(self):
        client = app.test_client()
        self.login(client)

        page = client.get("/home")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'class="mobile-menu-toggle"', page.data)
        self.assertIn(b'id="primary-navigation"', page.data)
        self.assertIn(b'href="/home" class="nav-link active">Home</a>', page.data)
        self.assertIn(b"Profile", page.data)
        self.assertIn(b'href="/profile/"', page.data)
        self.assertIn(b'class="user-account-link" href="/profile/"', page.data)
        self.assertIn(b"Test Student", page.data)

        script = client.get("/static/app/js/base.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn(b"initializeMobileNavigation", script.data)
        script.close()

    def test_profile_updates_contact_details_and_rejects_duplicate_email(self):
        with app.app_context():
            db.session.add(
                Profile(
                    id=2,
                    name="Other Student",
                    primary_email="other@example.com",
                    secondary_email="taken@example.com",
                    password_hash=generate_password_hash("password123"),
                    department="Testing",
                )
            )
            db.session.commit()

        client = app.test_client()
        self.login(client)
        profile_page = client.get("/profile/")
        self.assertEqual(profile_page.status_code, 200)
        self.assertIn(b"profile.css", profile_page.data)
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = client.post(
            "/profile/update",
            data={
                "_csrf_token": csrf,
                "name": "Updated Student",
                "phone_number": "+201012345678",
                "secondary_email": "backup@example.com",
                "primary_email": "changed@example.com",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Profile details updated.", response.data)
        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertEqual(profile.name, "Updated Student")
            self.assertEqual(profile.phone_number, "+201012345678")
            self.assertEqual(profile.secondary_email, "backup@example.com")
            self.assertEqual(profile.primary_email, "student@example.com")

        response = client.post(
            "/profile/update",
            data={
                "_csrf_token": csrf,
                "name": "Updated Student",
                "phone_number": "+201012345678",
                "secondary_email": "taken@example.com",
            },
            follow_redirects=True,
        )
        self.assertIn(b"already associated with another account", response.data)
        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertEqual(profile.secondary_email, "backup@example.com")

    def test_profile_password_change_verifies_old_password_and_hashes_new_password(self):
        client = app.test_client()
        self.login(client)
        client.get("/profile/")
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        bad_response = client.post(
            "/profile/password",
            data={
                "_csrf_token": csrf,
                "current_password": "wrong-password",
                "new_password": "ChangedPassword123",
                "confirm_password": "ChangedPassword123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"current password is incorrect", bad_response.data)

        response = client.post(
            "/profile/password",
            data={
                "_csrf_token": csrf,
                "current_password": "password123",
                "new_password": "ChangedPassword123",
                "confirm_password": "ChangedPassword123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Password updated successfully.", response.data)
        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertTrue(
                check_password_hash(profile.password_hash, "ChangedPassword123")
            )
        self.assertEqual(client.get("/profile/").status_code, 200)

    def test_profile_photo_upload_is_private_validated_and_removable(self):
        with TemporaryDirectory() as upload_folder, patch.dict(
            app.config,
            {"PROFILE_UPLOAD_FOLDER": upload_folder},
        ):
            client = app.test_client()
            self.login(client)
            client.get("/profile/")
            with client.session_transaction() as auth_session:
                csrf = auth_session["_csrf_token"]

            invalid_response = client.post(
                "/profile/photo",
                data={
                    "_csrf_token": csrf,
                    "profile_photo": (BytesIO(b"not an image"), "photo.png"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn(b"Choose a valid JPG or PNG photo.", invalid_response.data)

            oversized_response = client.post(
                "/profile/photo",
                data={
                    "_csrf_token": csrf,
                    "profile_photo": (
                        BytesIO(
                            b"\x89PNG\r\n\x1a\n"
                            + b"x" * (2 * 1024 * 1024 - 7)
                        ),
                        "large.png",
                    ),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn(b"2MB or smaller", oversized_response.data)

            photo_data = b"\x89PNG\r\n\x1a\nprofile-image-data"
            response = client.post(
                "/profile/photo",
                data={
                    "_csrf_token": csrf,
                    "profile_photo": (BytesIO(photo_data), "photo.png"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 302)
            with app.app_context():
                profile = db.session.get(Profile, 1)
                filename = profile.profile_image_url
            self.assertIsNotNone(filename)

            photo_response = client.get(f"/profile/photo/{filename}")
            self.assertEqual(photo_response.status_code, 200)
            self.assertEqual(photo_response.data, photo_data)
            photo_response.close()

            unauthorized_client = app.test_client()
            self.assertEqual(
                unauthorized_client.get(f"/profile/photo/{filename}").status_code,
                302,
            )

            remove_response = client.post(
                "/profile/photo",
                data={"_csrf_token": csrf, "action": "remove"},
                follow_redirects=True,
            )
            self.assertIn(b"Profile photo removed.", remove_response.data)
            with app.app_context():
                profile = db.session.get(Profile, 1)
                self.assertIsNone(profile.profile_image_url)
            self.assertFalse((Path(upload_folder) / filename).exists())

    def test_fifth_wrong_password_locks_account_for_15_minutes(self):
        client = app.test_client()
        for _ in range(5):
            self.login(client, password="wrong-password")

        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertEqual(profile.failed_login_attempts, 5)
            self.assertIsNotNone(profile.login_locked_until)
            seconds_remaining = (profile.login_locked_until - utc_now()).total_seconds()
            self.assertGreater(seconds_remaining, 890)
            self.assertLessEqual(seconds_remaining, 900)

        response = self.login(client, password="password123")
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as auth_session:
            self.assertNotIn("profile_id", auth_session)

    def test_login_succeeds_after_lockout_expires_and_resets_counter(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            profile.failed_login_attempts = 5
            profile.login_locked_until = utc_now() - timedelta(seconds=1)
            db.session.commit()

        client = app.test_client()
        response = self.login(client)
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertEqual(profile.failed_login_attempts, 0)
            self.assertIsNone(profile.login_locked_until)
            self.assertIsNotNone(profile.tokens)

    def test_password_reset_sends_15_minute_otp_and_updates_password_hash(self):
        client = app.test_client()
        with patch("routes.auth_pages.send_password_reset_email") as send_email:
            response = client.post(
                "/forgot-password",
                data={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        recipient, otp = send_email.call_args.args
        self.assertEqual(recipient, "student@example.com")
        self.assertEqual(len(otp), 6)

        with app.app_context():
            reset_entry = PasswordReset.query.filter_by(profile_id=1).first()
            self.assertTrue(check_password_hash(reset_entry.code, otp))
            seconds_remaining = (reset_entry.expires_at - utc_now()).total_seconds()
            self.assertGreater(seconds_remaining, 890)
            self.assertLessEqual(seconds_remaining, 900)

        response = client.post("/verify-otp", data={"digits": list(otp)})
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            reset_entry = PasswordReset.query.filter_by(profile_id=1).first()
            self.assertFalse(check_password_hash(reset_entry.code, otp))

        new_password = "ChangedPass123!"
        response = client.post(
            "/reset-password",
            data={"password": new_password, "confirm": new_password},
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            profile = db.session.get(Profile, 1)
            self.assertNotEqual(profile.password_hash, new_password)
            self.assertTrue(check_password_hash(profile.password_hash, new_password))
            self.assertEqual(profile.password_resets, [])

    def test_password_reset_mail_uses_outlook_starttls(self):
        with app.test_request_context("/"):
            with patch("services.password_reset_email.smtplib.SMTP") as smtp_factory:
                send_password_reset_email("student@example.com", "123456")

        smtp_factory.assert_called_once_with(
            OUTLOOK_SMTP_SERVER,
            OUTLOOK_SMTP_PORT,
            timeout=15,
        )
        smtp = smtp_factory.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(
            "student-hub@outlook.com",
            "test-mail-app-password",
        )
        sent_message = smtp.send_message.call_args.args[0]
        self.assertEqual(sent_message["To"], "student@example.com")
        self.assertIn("123456", sent_message.get_body(preferencelist=("plain",)).get_content())

    def test_password_reset_mail_uses_gmail_starttls(self):
        app.config["MAIL_EMAIL"] = "studenthub@gmail.com"
        app.config["MAIL_APP_PASSWORD"] = "test-gmail-app-password"

        with app.test_request_context("/"):
            with patch("services.password_reset_email.smtplib.SMTP") as smtp_factory:
                send_password_reset_email("student@example.com", "123456")

        smtp_factory.assert_called_once_with(
            GMAIL_SMTP_SERVER,
            GMAIL_SMTP_PORT,
            timeout=15,
        )
        smtp = smtp_factory.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(
            "studenthub@gmail.com",
            "test-gmail-app-password",
        )

    def test_admin_can_assign_ta_department_role(self):
        with app.app_context():
            admin = db.session.get(Profile, 1)
            admin.role = "admin"
            db.session.add(
                Profile(
                    id=2,
                    name="Test TA",
                    primary_email="ta@example.com",
                    password_hash=generate_password_hash("password123"),
                    department="Testing",
                )
            )
            db.session.commit()

        student_client = app.test_client()
        self.login(student_client, email="ta@example.com")
        self.assertEqual(student_client.get("/admin/roles/").status_code, 403)
        self.assertEqual(
            student_client.post("/admin/roles/create").status_code,
            403,
        )

        admin_client = app.test_client()
        self.login(admin_client)
        self.assertEqual(admin_client.get("/admin/roles/").status_code, 200)
        with admin_client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = admin_client.post(
            "/admin/roles/2",
            data={"role": "ta:ARC", "_csrf_token": csrf},
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            profile = db.session.get(Profile, 2)
            self.assertEqual(profile.role, "ta:ARC")

    def test_admin_can_edit_existing_account_details_and_password(self):
        with app.app_context():
            admin = db.session.get(Profile, 1)
            admin.role = "admin"
            db.session.add(
                Profile(
                    id=2,
                    name="Existing Student",
                    primary_email="existing@example.com",
                    password_hash=generate_password_hash("password123"),
                    role="student",
                    department="MIE",
                    tokens="active-session-token",
                )
            )
            db.session.commit()

        admin_client = app.test_client()
        self.login(admin_client)
        admin_client.get("/admin/roles/")
        with admin_client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = admin_client.post(
            "/admin/roles/2/edit",
            data={
                "name": "Updated Account",
                "email": "updated@example.com",
                "secondary_email": "backup@example.com",
                "phone_number": "+201234567890",
                "student_id": "UNI-2002",
                "department": "CSE",
                "role": "ta:CSE",
                "password": "NewSecurePassword123",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            profile = db.session.get(Profile, 2)
            self.assertEqual(profile.name, "Updated Account")
            self.assertEqual(profile.primary_email, "updated@example.com")
            self.assertEqual(profile.secondary_email, "backup@example.com")
            self.assertEqual(profile.phone_number, "+201234567890")
            self.assertEqual(profile.student_id, "UNI-2002")
            self.assertEqual(profile.role, "ta:CSE")
            self.assertEqual(profile.department, "CSE")
            self.assertTrue(
                check_password_hash(profile.password_hash, "NewSecurePassword123")
            )
            self.assertIsNone(profile.tokens)

    def test_admin_account_edit_rejects_duplicate_contact_email(self):
        with app.app_context():
            admin = db.session.get(Profile, 1)
            admin.role = "admin"
            db.session.add(
                Profile(
                    id=2,
                    name="Existing Student",
                    primary_email="existing@example.com",
                    password_hash=generate_password_hash("password123"),
                    department="MIE",
                )
            )
            db.session.commit()

        admin_client = app.test_client()
        self.login(admin_client)
        admin_client.get("/admin/roles/")
        with admin_client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = admin_client.post(
            "/admin/roles/2/edit",
            data={
                "name": "Existing Student",
                "email": "student@example.com",
                "department": "MIE",
                "role": "student",
                "_csrf_token": csrf,
            },
            follow_redirects=True,
        )
        self.assertIn(b"already associated with another account", response.data)
        with app.app_context():
            profile = db.session.get(Profile, 2)
            self.assertEqual(profile.primary_email, "existing@example.com")

    def test_admin_can_create_account_with_hashed_password_and_role(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            profile.role = "admin"
            db.session.commit()

        admin_client = app.test_client()
        self.login(admin_client)
        events_page = admin_client.get("/events")
        self.assertEqual(events_page.status_code, 302)
        self.assertEqual(events_page.location, "/events/manage/")
        roles_page = admin_client.get("/admin/roles/")
        self.assertEqual(roles_page.status_code, 200)
        self.assertIn(b'href="/events/manage/" class="nav-link', roles_page.data)
        self.assertNotIn(b">Manage Events</a>", roles_page.data)
        self.assertIn(b'id="create-account-dialog"', roles_page.data)
        self.assertIn(b'name="student_id"', roles_page.data)
        self.assertIn(b'<select id="new-department" name="department" required>', roles_page.data)
        self.assertIn(b"Electronics and Communications Engineering (EEC)", roles_page.data)
        self.assertLess(
            roles_page.data.index(b">Lost &amp; Found</a>"),
            roles_page.data.index(b">Manage Roles</a>"),
        )
        self.assertIn(b'class="role-row"', roles_page.data)
        self.assertIn(b">Edit</button>", roles_page.data)
        self.assertIn(b"Save changes", roles_page.data)
        css_response = admin_client.get("/static/app/css/admin-roles.css")
        self.assertEqual(css_response.status_code, 200)
        css_response.close()
        js_response = admin_client.get("/static/app/js/admin-roles.js")
        self.assertEqual(js_response.status_code, 200)
        js_response.close()
        with admin_client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        account_data = {
            "name": "New Teaching Assistant",
            "email": " TA@example.com ",
            "password": "SecurePassword123",
            "role": "ta:CSE",
            "student_id": "UNI-2026001",
            "department": "CSE",
            "_csrf_token": csrf,
        }
        response = admin_client.post("/admin/roles/create", data=account_data)
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            profile = Profile.query.filter_by(primary_email="ta@example.com").one()
            self.assertEqual(profile.name, "New Teaching Assistant")
            self.assertEqual(profile.role, "ta:CSE")
            self.assertEqual(profile.department, "CSE")
            self.assertEqual(profile.student_id, "UNI-2026001")
            self.assertTrue(
                check_password_hash(profile.password_hash, "SecurePassword123")
            )

        login_client = app.test_client()
        login_response = self.login(
            login_client,
            email="ta@example.com",
            password="SecurePassword123",
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_client.get("/events").status_code, 200)

        duplicate_response = admin_client.post(
            "/admin/roles/create",
            data=account_data,
            follow_redirects=True,
        )
        self.assertIn(b"An account with that email already exists.", duplicate_response.data)
        with app.app_context():
            self.assertEqual(
                Profile.query.filter_by(primary_email="ta@example.com").count(),
                1,
            )

        duplicate_id_data = {**account_data, "email": "another@example.com"}
        duplicate_id_response = admin_client.post(
            "/admin/roles/create",
            data=duplicate_id_data,
            follow_redirects=True,
        )
        self.assertIn(
            b"An account with that University ID already exists.",
            duplicate_id_response.data,
        )
        with app.app_context():
            self.assertIsNone(
                Profile.query.filter_by(primary_email="another@example.com").first()
            )

        invalid_department_data = {
            **account_data,
            "name": "Invalid Department",
            "email": "invalid-department@example.com",
            "role": "student",
            "student_id": "",
            "department": "Testing",
        }
        invalid_department_response = admin_client.post(
            "/admin/roles/create",
            data=invalid_department_data,
            follow_redirects=True,
        )
        self.assertIn(b"Choose a valid department.", invalid_department_response.data)
        with app.app_context():
            self.assertIsNone(
                Profile.query.filter_by(
                    primary_email="invalid-department@example.com"
                ).first()
            )

        valid_department_data = {
            **invalid_department_data,
            "name": "Assigned Department",
            "email": "assigned-department@example.com",
            "department": "MIE",
        }
        valid_department_response = admin_client.post(
            "/admin/roles/create",
            data=valid_department_data,
        )
        self.assertEqual(valid_department_response.status_code, 302)
        with app.app_context():
            created_profile = Profile.query.filter_by(
                primary_email="assigned-department@example.com"
            ).one()
            self.assertEqual(created_profile.department, "MIE")

    def test_student_lab_page_uses_browse_layout_without_management_actions(self):
        with app.app_context():
            db.session.add(
                Lab(
                    id=1,
                    name="CSE Lab",
                    department="CSE",
                    capacity=20,
                    room="101",
                )
            )
            db.session.commit()

        client = app.test_client()
        self.login(client)
        labs_page = client.get("/labs")

        self.assertEqual(labs_page.status_code, 200)
        self.assertIn(b"lab-filters", labs_page.data)
        self.assertIn(b"lab-grid", labs_page.data)
        self.assertIn(b"CSE Lab", labs_page.data)
        self.assertIn(b"labs-admin.css", labs_page.data)
        self.assertNotIn(b"Manage lab", labs_page.data)
        self.assertNotIn(b"+ Add lab", labs_page.data)

    def test_student_events_page_places_search_with_filters(self):
        client = app.test_client()
        self.login(client)
        events_page = client.get("/events")

        self.assertEqual(events_page.status_code, 200)
        self.assertIn(b'class="events-student"', events_page.data)
        self.assertIn(b'class="events-container"', events_page.data)
        self.assertLess(
            events_page.data.index(b'class="events-filters"'),
            events_page.data.index(b'id="eventSearchInput"'),
        )

    def test_student_events_page_shows_low_seat_badges(self):
        with app.app_context():
            db.session.add_all(
                [
                    Event(
                        id=1,
                        event_name="Nearly Full Workshop",
                        organizer="Engineering Society",
                        location="Room 12",
                        date=date.today() + timedelta(days=1),
                        start_time=time_of_day(10),
                        end_time=time_of_day(12),
                        capacity=10,
                        category="Workshop",
                    ),
                    Event(
                        id=2,
                        event_name="Open Seminar",
                        organizer="Engineering Society",
                        location="Room 13",
                        date=date.today() + timedelta(days=2),
                        start_time=time_of_day(10),
                        end_time=time_of_day(12),
                        capacity=11,
                        category="Seminar",
                    ),
                    Event(
                        id=3,
                        event_name="Last Seat Talk",
                        organizer="Engineering Society",
                        location="Room 14",
                        date=date.today() + timedelta(days=3),
                        start_time=time_of_day(10),
                        end_time=time_of_day(12),
                        capacity=1,
                        category="Seminar",
                    ),
                ]
            )
            db.session.commit()

        client = app.test_client()
        self.login(client)
        events_page = client.get("/events")

        self.assertIn(b"class=\"spots-left-badge\">10 spots left", events_page.data)
        self.assertIn(b"Capacity: <strong>11</strong> seats", events_page.data)
        self.assertIn(b"class=\"spots-left-badge\">1 spot left", events_page.data)

    def test_student_can_star_and_unstar_event_from_events_list(self):
        with app.app_context():
            db.session.add(
                Event(
                    id=1,
                    event_name="Systems Workshop",
                    organizer="Engineering Society",
                    location="Room 12",
                    date=date.today() + timedelta(days=1),
                    start_time=time_of_day(10),
                    end_time=time_of_day(12),
                    capacity=25,
                    category="Workshop",
                )
            )
            db.session.commit()

        client = app.test_client()
        self.login(client)
        events_page = client.get("/events")
        self.assertIn(b"Add Systems Workshop to starred events", events_page.data)
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        self.assertEqual(client.post("/events/1/star").status_code, 400)
        response = client.post(
            "/events/1/star",
            data={"_csrf_token": csrf},
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertIsNotNone(
                StarredEvent.query.filter_by(profile_id=1, event_id=1).first()
            )

        starred_page = client.get("/events")
        self.assertIn(b"aria-pressed=\"true\"", starred_page.data)
        response = client.post(
            "/events/1/star",
            data={"_csrf_token": csrf},
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertIsNone(
                StarredEvent.query.filter_by(profile_id=1, event_id=1).first()
            )

    def test_ta_can_manage_only_matching_department_labs(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            profile.role = "ta:CSE"
            db.session.add_all(
                [
                    Lab(
                        id=1,
                        name="CSE Lab",
                        department="CSE",
                        capacity=20,
                        room="101",
                    ),
                    Lab(
                        id=2,
                        name="EEC Lab",
                        department="EEC",
                        capacity=20,
                        room="102",
                    ),
                ]
            )
            db.session.commit()

        client = app.test_client()
        self.login(client)
        labs_page = client.get("/labs")
        self.assertEqual(labs_page.status_code, 200)
        self.assertIn(b"Manage Labs", labs_page.data)
        self.assertIn(b"labs-admin.css", labs_page.data)
        css_response = client.get("/static/app/css/labs-admin.css")
        self.assertEqual(css_response.status_code, 200)
        css_response.close()
        self.assertEqual(client.get("/labs/1/edit").status_code, 200)
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        denied = client.post(
            "/labs/2/update",
            data={
                "name": "Changed EEC Lab",
                "room": "102",
                "capacity": "20",
                "status": "available",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(denied.status_code, 403)

        response = client.post(
            "/labs",
            data={
                "name": "Created by CSE TA",
                "room": "103",
                "capacity": "15",
                "status": "available",
                "department": "EEC",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            lab = Lab.query.filter_by(name="Created by CSE TA").one()
            self.assertEqual(lab.department, "CSE")

    def test_admin_can_create_edit_lab_and_manage_slots(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            profile.role = "admin"
            db.session.commit()

        client = app.test_client()
        self.login(client)
        new_lab_page = client.get("/labs/new")
        self.assertEqual(new_lab_page.status_code, 200)
        with client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = client.post(
            "/labs",
            data={
                "name": "Design Lab",
                "room": "B-204",
                "capacity": "20",
                "status": "available",
                "department": "CSE",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/labs/1/saved", response.location)
        self.assertIn(b"Lab created.", client.get(response.location).data)

        edit_page = client.get("/labs/1/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Design Lab", edit_page.data)
        response = client.post(
            "/labs/1/update",
            data={
                "name": "Design and Computing Lab",
                "room": "B-204",
                "capacity": "20",
                "status": "available",
                "department": "CSE",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/labs/1/saved", response.location)
        self.assertIn(b"Lab updated.", client.get(response.location).data)

        response = client.post(
            "/labs/1/slots",
            data={
                "date": "2026-12-20",
                "start_time": "09:00",
                "end_time": "10:00",
                "capacity": "10",
                "availability": "available",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            lab = Lab.query.filter_by(name="Design and Computing Lab").one()
            slot = LabSlot.query.filter_by(lab_id=lab.id).one()
            lab_id = lab.id
            slot_id = slot.id
        self.assertIn(f"/labs/{lab_id}/saved?slot_id={slot_id}", response.location)

        edit_slot = client.get(
            f"/labs/{lab_id}/edit?slot_id={slot_id}"
        )
        self.assertEqual(edit_slot.status_code, 200)
        self.assertIn(b"Edit slot", edit_slot.data)
        response = client.post(
            f"/labs/{lab_id}/slots/{slot_id}/update",
            data={
                "date": "2026-12-21",
                "start_time": "10:00",
                "end_time": "11:00",
                "capacity": "12",
                "availability": "unavailable",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        saved_page = client.get(response.location)
        self.assertEqual(saved_page.status_code, 200)
        self.assertIn(b"Changes saved", saved_page.data)
        with app.app_context():
            slot = db.session.get(LabSlot, slot_id)
            self.assertEqual(slot.date.isoformat(), "2026-12-21")
            self.assertFalse(slot.is_active)

    def test_event_manager_can_create_events_but_student_cannot_manage_them(self):
        with app.app_context():
            profile = db.session.get(Profile, 1)
            profile.role = "event_manager"
            db.session.add(
                Profile(
                    id=2,
                    name="Test Student Two",
                    primary_email="student2@example.com",
                    password_hash=generate_password_hash("password123"),
                    department="Testing",
                )
            )
            db.session.commit()

        student_client = app.test_client()
        self.login(student_client, email="student2@example.com")
        self.assertEqual(student_client.get("/events/manage/").status_code, 403)
        self.assertEqual(student_client.get("/events").status_code, 200)

        manager_client = app.test_client()
        self.login(manager_client)
        events_page = manager_client.get("/events")
        self.assertEqual(events_page.status_code, 302)
        self.assertEqual(events_page.location, "/events/manage/")
        self.assertEqual(
            manager_client.get("/events/1").location,
            "/events/manage/",
        )
        new_event_page = manager_client.get("/events/manage/new")
        self.assertEqual(new_event_page.status_code, 200)
        self.assertIn(b"events-admin.css", new_event_page.data)
        self.assertIn(
            b'href="/events/manage/"',
            new_event_page.data,
        )
        self.assertNotIn(b">Manage Events</a>", new_event_page.data)
        self.assertIn(b"Add event", new_event_page.data)
        css_response = manager_client.get("/static/app/css/events-admin.css")
        self.assertEqual(css_response.status_code, 200)
        with manager_client.session_transaction() as auth_session:
            csrf = auth_session["_csrf_token"]

        response = manager_client.post(
            "/events/manage/",
            data={
                "event_name": "Systems Workshop",
                "organizer": "Engineering Society",
                "location": "Room 12",
                "category": "Workshop",
                "date": "2026-12-01",
                "start_time": "10:00",
                "end_time": "12:00",
                "capacity": "25",
                "registration_status": "open",
                "agenda": "Intro",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            event = Event.query.filter_by(event_name="Systems Workshop").one()
            event_id = event.id
        self.assertEqual(
            response.location,
            f"/events/manage/{event_id}/saved",
        )
        self.assertEqual(
            manager_client.post(f"/events/{event_id}").location,
            "/events/manage/",
        )

        saved_page = manager_client.get(response.location)
        self.assertEqual(saved_page.status_code, 200)
        self.assertIn(b"Event created.", saved_page.data)

        edit_page = manager_client.get(f"/events/manage/{event_id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Systems Workshop", edit_page.data)

        response = manager_client.post(
            f"/events/manage/{event_id}",
            data={
                "event_name": "Systems Workshop Updated",
                "organizer": "Engineering Society",
                "location": "Room 12",
                "category": "Workshop",
                "date": "2026-12-01",
                "start_time": "10:00",
                "end_time": "12:00",
                "capacity": "25",
                "registration_status": "open",
                "agenda": "Intro",
                "_csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/events/manage/{event_id}/saved", response.location)
        self.assertIn(
            b"Event updated.",
            manager_client.get(response.location).data,
        )

        manage_page = manager_client.get("/events/manage/")
        self.assertEqual(manage_page.status_code, 200)
        self.assertIn(b"Systems Workshop Updated", manage_page.data)
        with app.app_context():
            event = Event.query.filter_by(
                event_name="Systems Workshop Updated"
            ).one()
            self.assertEqual(event.organizer, "Engineering Society")


if __name__ == "__main__":
    unittest.main()
