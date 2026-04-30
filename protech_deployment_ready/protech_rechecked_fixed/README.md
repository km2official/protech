# Protech Deployment Ready

Flask + SQLite + Admin Dashboard + User Service Requests.

## 1. Install packages

```bash
pip install -r requirements.txt
```

## 2. Configure environment

Copy `.env.example` to `.env` and change values:

```bash
cp .env.example .env
```

Example values:

```env
SECRET_KEY=replace-with-a-long-random-secret-key
ADMIN_EMAIL=your-admin-email@example.com
ADMIN_PASSWORD=your-strong-admin-password
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=0
PORT=5000
```

For HTTPS deployment, set:

```env
SESSION_COOKIE_SECURE=1
```

## 3. Run locally

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## 4. Production run with Gunicorn

```bash
gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app
```

## 5. EC2 security group

Allow:

```text
Custom TCP | 5000 | 0.0.0.0/0
```

Then open:

```text
http://YOUR-EC2-PUBLIC-IP:5000
```

## Notes

- `database.db` is created automatically on first run.
- Profile pictures are saved in `static/profile_pics/`.
- Admin credentials are read from `.env` / environment variables.
- Contact email:protechwithcloud@gmail.com
