from flask import Flask, render_template, request, jsonify, session, url_for
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import re
import sqlite3
from datetime import datetime

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "database.db")
PROFILE_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "profile_pics")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "protech-dev-secret-key-change-this")
app.config["PROFILE_UPLOAD_FOLDER"] = PROFILE_UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

# Same-origin frontend works without CORS. Keep credentials enabled for local/API testing.
CORS(app, supports_credentials=True)

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@protech.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
PHONE_RE = re.compile(r"^\d{10}$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,24}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(cur, table_name, column_name):
    cur.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cur.fetchall())


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password TEXT NOT NULL,
            profile_pic TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS service_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            web_development INTEGER DEFAULT 0,
            cloud_solutions INTEGER DEFAULT 0,
            cyber_security INTEGER DEFAULT 0,
            details TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Safe migration for older DB files.
    if not column_exists(cur, "users", "profile_pic"):
        cur.execute("ALTER TABLE users ADD COLUMN profile_pic TEXT")
    if not column_exists(cur, "users", "created_at"):
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    if not column_exists(cur, "service_requests", "updated_at"):
        cur.execute("ALTER TABLE service_requests ADD COLUMN updated_at TEXT")

    conn.commit()
    conn.close()


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def current_user_id():
    if session.get("role") == "user":
        return session.get("user_id")
    return None


init_db()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/me", methods=["GET"])
def me():
    if session.get("role") == "admin":
        return jsonify({"logged_in": True, "role": "admin"}), 200

    user_id = current_user_id()
    if not user_id:
        return jsonify({"logged_in": False}), 200

    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, name, email, phone, profile_pic, created_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    active_request = conn.execute(
        """
        SELECT id, status, created_at, updated_at
        FROM service_requests
        WHERE user_id = ? AND status != 'Completed'
        ORDER BY id DESC LIMIT 1
        """,
        (user_id,)
    ).fetchone()
    conn.close()

    if not user:
        session.clear()
        return jsonify({"logged_in": False}), 200

    profile_url = url_for("static", filename=f"profile_pics/{user['profile_pic']}") if user["profile_pic"] else None

    return jsonify({
        "logged_in": True,
        "role": "user",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user["phone"],
            "profile_pic": profile_url,
            "created_at": user["created_at"]
        },
        "active_request": dict(active_request) if active_request else None
    }), 200


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")

    if not name or not email or not phone or not password:
        return jsonify({"error": "All fields are required"}), 400

    if not EMAIL_RE.fullmatch(email):
        return jsonify({"error": "Enter a valid email address"}), 400

    if not PHONE_RE.fullmatch(phone):
        return jsonify({"error": "Phone number must be exactly 10 digits"}), 400

    if not PASSWORD_RE.fullmatch(password):
        return jsonify({"error": "Password must be 6 to 24 characters and include letters, numbers, and a symbol"}), 400

    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (name, email, phone, password, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, phone, generate_password_hash(password), now_stamp())
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Registration successful. Please login."}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already exists"}), 409
    except Exception as e:
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, name, email, phone, password, profile_pic, created_at FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        session.clear()
        session["role"] = "user"
        session["user_id"] = user["id"]

        profile_url = url_for("static", filename=f"profile_pics/{user['profile_pic']}") if user["profile_pic"] else None

        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "phone": user["phone"],
                "profile_pic": profile_url,
                "created_at": user["created_at"]
            }
        }), 200

    return jsonify({"error": "Invalid email or password"}), 401


@app.route("/admin-login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
        session.clear()
        session["role"] = "admin"
        return jsonify({"message": "Admin login successful"}), 200

    return jsonify({"error": "Invalid admin credentials"}), 401


@app.route("/profile-picture", methods=["POST"])
def upload_profile_picture():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Please login first"}), 401

    if "profile_pic" not in request.files:
        return jsonify({"error": "No image selected"}), 400

    image = request.files["profile_pic"]
    if image.filename == "":
        return jsonify({"error": "No image selected"}), 400

    if not allowed_image(image.filename):
        return jsonify({"error": "Only png, jpg, jpeg, gif, webp files are allowed"}), 400

    safe_name = secure_filename(image.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()
    filename = f"user_{user_id}_{int(datetime.now().timestamp())}.{ext}"
    filepath = os.path.join(PROFILE_UPLOAD_FOLDER, filename)

    conn = get_db_connection()
    old = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()

    image.save(filepath)
    conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (filename, user_id))
    conn.commit()
    conn.close()

    if old and old["profile_pic"]:
        old_path = os.path.join(PROFILE_UPLOAD_FOLDER, old["profile_pic"])
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    return jsonify({
        "message": "Profile picture updated",
        "profile_pic": url_for("static", filename=f"profile_pics/{filename}")
    }), 200


@app.route("/profile-picture", methods=["DELETE"])
def remove_profile_picture():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Please login first"}), 401

    conn = get_db_connection()
    user = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.execute("UPDATE users SET profile_pic = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    if user and user["profile_pic"]:
        path = os.path.join(PROFILE_UPLOAD_FOLDER, user["profile_pic"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    return jsonify({"message": "Profile picture removed"}), 200


@app.route("/service-request", methods=["POST"])
def service_request():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Please login as user first"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    conn = get_db_connection()
    active = conn.execute(
        "SELECT id, status FROM service_requests WHERE user_id = ? AND status != 'Completed' ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()

    if active:
        conn.close()
        return jsonify({
            "error": "You already submitted a request. Services are temporarily closed for your account until admin marks it completed."
        }), 409

    web_development = 1 if data.get("web_development") else 0
    cloud_solutions = 1 if data.get("cloud_solutions") else 0
    cyber_security = 1 if data.get("cyber_security") else 0
    details = data.get("details", "").strip()

    if not (web_development or cloud_solutions or cyber_security):
        conn.close()
        return jsonify({"error": "Please select at least one service"}), 400

    if not details:
        conn.close()
        return jsonify({"error": "Please enter brief details"}), 400

    stamp = now_stamp()
    conn.execute(
        """
        INSERT INTO service_requests
        (user_id, web_development, cloud_solutions, cyber_security, details, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?)
        """,
        (user_id, web_development, cloud_solutions, cyber_security, details, stamp, stamp)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Service request submitted successfully", "created_at": stamp}), 201


@app.route("/my-requests", methods=["GET"])
def my_requests():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Please login first"}), 401

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, web_development, cloud_solutions, cyber_security, details, status, created_at, updated_at
        FROM service_requests
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows]), 200


@app.route("/admin/requests", methods=["GET"])
def admin_requests():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            service_requests.id,
            users.name,
            users.email,
            users.phone,
            users.profile_pic,
            service_requests.web_development,
            service_requests.cloud_solutions,
            service_requests.cyber_security,
            service_requests.details,
            service_requests.status,
            service_requests.created_at,
            service_requests.updated_at
        FROM service_requests
        JOIN users ON service_requests.user_id = users.id
        ORDER BY service_requests.created_at DESC
        """
    ).fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append({
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "profile_pic": url_for("static", filename=f"profile_pics/{row['profile_pic']}") if row["profile_pic"] else None,
            "web_development": bool(row["web_development"]),
            "cloud_solutions": bool(row["cloud_solutions"]),
            "cyber_security": bool(row["cyber_security"]),
            "details": row["details"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        })

    return jsonify(data), 200


@app.route("/admin/requests/<int:request_id>/status", methods=["POST"])
def update_request_status(request_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    status = data.get("status")
    allowed_statuses = {"Pending", "Approved", "Rejected", "Completed"}
    if status not in allowed_statuses:
        return jsonify({"error": "Invalid status"}), 400

    conn = get_db_connection()
    cur = conn.execute(
        "UPDATE service_requests SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_stamp(), request_id)
    )
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Request not found"}), 404

    return jsonify({"message": "Status updated successfully"}), 200


@app.route("/stats", methods=["GET"])
def stats():
    conn = get_db_connection()
    completed_projects = conn.execute(
        "SELECT COUNT(*) AS count FROM service_requests WHERE status = 'Completed'"
    ).fetchone()["count"]
    conn.close()

    return jsonify({"completed_projects": completed_projects}), 200


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
