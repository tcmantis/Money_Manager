import sqlite3
from flask import Flask, render_template, request, redirect, session, jsonify
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change_this_secret_key"

app.config["JWT_SECRET_KEY"] = "super-secret-mobile-key"
jwt = JWTManager(app)

DB_NAME = "money_manager.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        category TEXT NOT NULL,
        amount REAL NOT NULL,
        user_id INTEGER,
        balance REAL
    )
    """)

    try:
        cursor.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE transactions ADD COLUMN balance REAL")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
    INSERT OR IGNORE INTO users (username, password_hash)
    VALUES (?, ?)
    """, ("Travis", generate_password_hash("password123")))

    conn.commit()
    conn.close()


def get_months():
    return [
        (1, "January"), (2, "February"), (3, "March"),
        (4, "April"), (5, "May"), (6, "June"),
        (7, "July"), (8, "August"), (9, "September"),
        (10, "October"), (11, "November"), (12, "December")
    ]


def get_selected_month():
    selected_month = int(request.args.get("month", session.get("selected_month", 1)))
    session["selected_month"] = selected_month
    return selected_month


@app.route("/login", methods=["GET", "POST"])
def login():
    setup_database()

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["selected_month"] = session.get("selected_month", 1)
            return redirect(f"/?month={session['selected_month']}")

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/", methods=["GET", "POST"])
def index():
    setup_database()

    if "user_id" not in session:
        return redirect("/login")

    selected_user_id = session["user_id"]
    selected_month = get_selected_month()

    if request.method == "POST":
        date = request.form["date"]
        category = request.form["category"]
        amount = float(request.form["amount"])
        transaction_type = request.form["type"]

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO transactions (date, type, category, amount, user_id)
        VALUES (?, ?, ?, ?, ?)
        """, (date, transaction_type, category, amount, selected_user_id))

        conn.commit()
        conn.close()

        return redirect(f"/?month={selected_month}")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM transactions
    WHERE type = 'income'
    AND user_id = ?
    AND CAST(strftime('%m', date) AS INTEGER) = ?
    ORDER BY date
    """, (selected_user_id, selected_month))
    incomes = cursor.fetchall()

    cursor.execute("""
    SELECT *
    FROM transactions
    WHERE type = 'expense'
    AND user_id = ?
    AND CAST(strftime('%m', date) AS INTEGER) = ?
    ORDER BY date
    """, (selected_user_id, selected_month))
    expenses = cursor.fetchall()

    cursor.execute("""
    SELECT DISTINCT category
    FROM transactions
    WHERE type = 'expense'
    AND user_id = ?
    ORDER BY category
    """, (selected_user_id,))
    expense_categories = cursor.fetchall()

    total_income = sum(row["amount"] for row in incomes)
    total_expenses = sum(row["amount"] for row in expenses)
    balance = total_income - total_expenses

    running_balance = total_income
    expense_summary = []

    for expense in expenses:
        if expense["balance"] is not None:
            running_balance = expense["balance"]
        else:
            running_balance -= expense["amount"]

        expense_summary.append({
            "date": expense["date"],
            "category": expense["category"],
            "amount": expense["amount"],
            "new_balance": running_balance
        })

    conn.close()

    return render_template(
        "index.html",
        username=session["username"],
        incomes=incomes,
        expenses=expenses,
        expense_summary=expense_summary,
        expense_categories=expense_categories,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        months=get_months(),
        selected_month=selected_month
    )


@app.route("/monthly_summary")
def monthly_summary():
    setup_database()

    if "user_id" not in session:
        return redirect("/login")

    selected_user_id = session["user_id"]
    selected_month = get_selected_month()
    end_month = selected_month + 2

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM transactions
    WHERE type = 'income'
    AND user_id = ?
    AND CAST(strftime('%m', date) AS INTEGER) BETWEEN ? AND ?
    ORDER BY date
    """, (selected_user_id, selected_month, end_month))
    incomes = cursor.fetchall()

    cursor.execute("""
    SELECT *
    FROM transactions
    WHERE type = 'expense'
    AND user_id = ?
    AND CAST(strftime('%m', date) AS INTEGER) BETWEEN ? AND ?
    ORDER BY date
    """, (selected_user_id, selected_month, end_month))
    expenses = cursor.fetchall()

    total_income = sum(row["amount"] for row in incomes)
    total_expenses = sum(row["amount"] for row in expenses)
    balance = total_income - total_expenses

    conn.close()

    return render_template(
        "monthly_summary.html",
        username=session["username"],
        incomes=incomes,
        expenses=expenses,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        months=get_months(),
        selected_month=selected_month
    )


@app.route("/add_user", methods=["POST"])
def add_user():
    username = request.form["username"]
    password = request.form["password"]

    password_hash = generate_password_hash(password)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO users (username, password_hash)
    VALUES (?, ?)
    """, (username, password_hash))

    conn.commit()
    conn.close()

    return redirect("/login")


@app.route("/edit/<int:transaction_id>", methods=["POST"])
def edit_transaction(transaction_id):
    if "user_id" not in session:
        return redirect("/login")

    date = request.form["date"]
    category = request.form["category"]
    amount = float(request.form["amount"])

    balance_value = request.form.get("balance")

    if balance_value:
        balance_value = float(balance_value)
    else:
        balance_value = None

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE transactions
    SET date = ?, category = ?, amount = ?, balance = ?
    WHERE id = ? AND user_id = ?
    """, (
        date,
        category,
        amount,
        balance_value,
        transaction_id,
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    return redirect(f"/?month={session.get('selected_month', 1)}")


@app.route("/api/login", methods=["POST"])
def api_login():
    setup_database()

    data = request.get_json()

    username = data.get("username")
    password = data.get("password")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    conn.close()

    if user and check_password_hash(user["password_hash"], password):
        access_token = create_access_token(identity=user["id"])

        return jsonify({
            "access_token": access_token,
            "username": user["username"]
        })

    return jsonify({"error": "Invalid username or password"}), 401


@app.route("/api/transactions")
@jwt_required()
def api_transactions():
    user_id = get_jwt_identity()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM transactions
    WHERE user_id = ?
    ORDER BY date
    """, (user_id,))

    rows = cursor.fetchall()
    conn.close()

    transactions = []

    for row in rows:
        transactions.append({
            "id": row["id"],
            "date": row["date"],
            "type": row["type"],
            "category": row["category"],
            "amount": row["amount"],
            "balance": row["balance"]
        })

    return jsonify(transactions)


if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=5000, debug=True)