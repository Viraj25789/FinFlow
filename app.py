import os
import io
import base64
import calendar
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, url_for, flash, redirect, Response, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from weasyprint import HTML

app = Flask(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'expenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'change-this-secret-key-for-production'

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ── Admin decorator ────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated

# ── Database Models ───────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    expenses      = db.relationship('Expense', backref='owner', lazy=True, cascade='all, delete-orphan')
    budgets       = db.relationship('Budget',  backref='owner', lazy=True, cascade='all, delete-orphan')
    incomes       = db.relationship('Income',  backref='owner', lazy=True, cascade='all, delete-orphan')
    goals         = db.relationship('SavingsGoal', backref='owner', lazy=True, cascade='all, delete-orphan')

class Expense(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(120), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    category    = db.Column(db.String(50), nullable=False)
    date        = db.Column(db.Date, nullable=False, default=date.today)
    note        = db.Column(db.String(255), nullable=True)          # NEW: optional note
    is_recurring= db.Column(db.Boolean, default=False)              # NEW: recurring flag
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Budget(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    limit    = db.Column(db.Float, nullable=False)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# NEW: Income model
class Income(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(120), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    source      = db.Column(db.String(50), nullable=False)   # Salary, Freelance, Other
    date        = db.Column(db.Date, nullable=False, default=date.today)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# NEW: Savings Goal model
class SavingsGoal(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(100), nullable=False)
    target      = db.Column(db.Float, nullable=False)
    saved       = db.Column(db.Float, default=0.0)
    deadline    = db.Column(db.Date, nullable=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    @property
    def percent(self):
        if not self.target or self.target <= 0:
            return 0
        return min(int(round((self.saved / self.target) * 100)), 100)

    @property
    def remaining(self):
        return max(float(self.target) - float(self.saved), 0.0)

with app.app_context():
    db.create_all()

# ── Constants ─────────────────────────────────────────────────────────────────
CATEGORIES     = ['Food', 'Transport', 'Rent', 'Utilities', 'Health', 'Other']
INCOME_SOURCES = ['Salary', 'Freelance', 'Business', 'Investment', 'Gift', 'Other']

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

def get_filtered_query(query, start, end, category):
    query = query.filter(Expense.user_id == current_user.id)
    if start:
        query = query.filter(Expense.date >= start)
    if end:
        query = query.filter(Expense.date <= end)
    if category:
        query = query.filter(Expense.category == category)
    return query

def ai_categorize(description):
    description = description.lower()
    rules = {
        'Food':      ['burger', 'pizza', 'coffee', 'groceries', 'dinner', 'lunch',
                      'breakfast', 'snack', 'restaurant', 'swiggy', 'zomato', 'food'],
        'Transport': ['uber', 'bus', 'fuel', 'gas', 'petrol', 'train', 'ticket',
                      'taxi', 'ola', 'auto', 'rickshaw', 'metro'],
        'Rent':      ['rent', 'house', 'apartment', 'mortgage', 'pg', 'hostel'],
        'Utilities': ['electric', 'water', 'bill', 'internet', 'wifi', 'phone',
                      'mobile', 'recharge', 'subscription', 'netflix', 'amazon'],
        'Health':    ['doctor', 'pharmacy', 'medicine', 'gym', 'hospital',
                      'dental', 'medical', 'clinic'],
        'Other':     []
    }
    for category, keywords in rules.items():
        if any(word in description for word in keywords):
            return category
    return 'Other'

def generate_chart_image(labels, values, title):
    if not values or sum(values) == 0:
        return None
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
    ax.set_title(title)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    # Lifetime totals
    lifetime_expense = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id).scalar() or 0
    lifetime_income  = db.session.query(func.sum(Income.amount)).filter(
        Income.user_id == current_user.id).scalar() or 0
    net_balance = round(lifetime_income - lifetime_expense, 2)

    today           = date.today()
    this_month_start= date(today.year, today.month, 1)
    _, days_in_month = calendar.monthrange(today.year, today.month)
    this_month_end  = date(today.year, today.month, days_in_month) 

    last_month_end  = this_month_start - timedelta(days=1)
    last_month_start= date(last_month_end.year, last_month_end.month, 1)

    # This Month's Expenses
    this_month_sum = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id,
        Expense.date >= this_month_start,
        Expense.date <= this_month_end).scalar() or 0

    # Last Month's Expenses
    last_month_sum = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id,
        Expense.date >= last_month_start,
        Expense.date <= last_month_end).scalar() or 0

    # This Month's Income
    this_month_income = db.session.query(func.sum(Income.amount)).filter(
        Income.user_id == current_user.id,
        Income.date >= this_month_start,
        Income.date <= this_month_end).scalar() or 0

    # --- NEW: This Month's Net Balance ---
    net_balance = round(this_month_income - this_month_sum, 2)

    diff_percent = 0
    diff_message = "No data for last month"
    diff_color   = "text-slate-400"
    

    if last_month_sum > 0:
        diff_percent = ((this_month_sum - last_month_sum) / last_month_sum) * 100
        if diff_percent > 0:
            diff_message = f"{abs(diff_percent):.0f}% MORE than last month"
            diff_color   = "text-rose-400"
        elif diff_percent < 0:
            diff_message = f"{abs(diff_percent):.0f}% LESS than last month"
            diff_color   = "text-emerald-400"
        else:
            diff_message = "Same as last month"

    # Prediction
    daily_avg      = this_month_sum / today.day if today.day > 0 else 0
    predicted_total= daily_avg * days_in_month
    prediction_msg = f"{predicted_total:,.0f}" # Cleaned up formatting

    # Recurring expenses count
    recurring_count = Expense.query.filter_by(
        user_id=current_user.id, is_recurring=True).count()

    # Recent 5 expenses for the sidebar
    recent_expenses = Expense.query.filter_by(user_id=current_user.id).order_by(
        Expense.date.desc(), Expense.id.desc()).limit(5).all()

    # Expense Categories Chart (This Month)
    cat_q = db.session.query(Expense.category, func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id, Expense.date >= this_month_start).group_by(Expense.category).all()
    cat_labels = [c for c, _ in cat_q]
    cat_values = [round(float(s or 0), 2) for _, s in cat_q]

    # --- NEW: Merged Daily Trend Data (Income vs Expense) ---
    exp_day_raw = db.session.query(Expense.date, func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id, Expense.date >= this_month_start).group_by(Expense.date).all()
    inc_day_raw = db.session.query(Income.date, func.sum(Income.amount)).filter(
        Income.user_id == current_user.id, Income.date >= this_month_start).group_by(Income.date).all()

    daily_data = {}
    
    # Map expenses to dates
    for d, amt in exp_day_raw:
        date_str = d.isoformat()
        if date_str not in daily_data:
            daily_data[date_str] = {'expense': 0, 'income': 0}
        daily_data[date_str]['expense'] = round(float(amt or 0), 2)
        
    # Map incomes to dates
    for d, amt in inc_day_raw:
        date_str = d.isoformat()
        if date_str not in daily_data:
            daily_data[date_str] = {'expense': 0, 'income': 0}
        daily_data[date_str]['income'] = round(float(amt or 0), 2)

    # Sort the dates chronologically for the chart X-axis
    sorted_dates = sorted(daily_data.keys())
    day_labels = sorted_dates
    day_exp_values = [daily_data[d]['expense'] for d in sorted_dates]
    day_inc_values = [daily_data[d]['income'] for d in sorted_dates]
    # ---------------------------------------------------------

    # Income Chart (This Month)
    inc_src_q = db.session.query(Income.source, func.sum(Income.amount)).filter(
        Income.user_id == current_user.id, Income.date >= this_month_start).group_by(Income.source).all()
    inc_src_labels = [s for s, _ in inc_src_q]
    inc_src_values = [round(float(v or 0), 2) for _, v in inc_src_q]

    return render_template("index.html",
        this_month_sum=this_month_sum,
        this_month_income=this_month_income,
        net_balance=net_balance,
        diff_message=diff_message,
        diff_color=diff_color,
        prediction_msg=prediction_msg,
        recurring_count=recurring_count,
        recent_expenses=recent_expenses,
        cat_labels=cat_labels,
        cat_values=cat_values,
        day_labels=day_labels,
        day_exp_values=day_exp_values,  # Updated!
        day_inc_values=day_inc_values,  # Updated!
        inc_src_labels=inc_src_labels,
        inc_src_values=inc_src_values,
    )

# ── INCOME ────────────────────────────────────────────────────────────────────
@app.route("/income", methods=['GET', 'POST'])
@login_required
def income():
    if request.method == 'POST':
        try:
            amount = float(request.form.get("amount", 0))
            if amount <= 0: raise ValueError
        except ValueError:
            flash("Invalid amount", "error")
            return redirect(url_for("income"))

        description = request.form.get("description", "").strip()
        source      = request.form.get("source", "Other")
        date_obj    = parse_date(request.form.get("date")) or date.today()

        db.session.add(Income(description=description, amount=amount,
                              source=source, date=date_obj,
                              user_id=current_user.id))
        db.session.commit()
        flash("Income added successfully", "success")
        return redirect(url_for("income"))

    incomes = Income.query.filter_by(user_id=current_user.id)\
                          .order_by(Income.date.desc()).all()
    total_income = sum(i.amount for i in incomes)

    # Net balance calculation
    total_expense = db.session.query(func.sum(Expense.amount))\
                              .filter(Expense.user_id == current_user.id).scalar() or 0
    net_balance = round(total_income - total_expense, 2)

    # Chart data is no longer processed here.
    return render_template("income.html",
        incomes=incomes, income_sources=INCOME_SOURCES,
        total_income=total_income, total_expense=total_expense,
        net_balance=net_balance,
        today=date.today().isoformat())

# ── EXPENSE CRUD ──────────────────────────────────────────────────────────────
@app.route("/expense", methods=['GET', 'POST'])
@login_required
def expense():
    if request.method == 'POST':
        try:
            amount = float(request.form.get("amount", 0))
            if amount <= 0: raise ValueError
        except ValueError:
            flash("Invalid amount", "error")
            return redirect(url_for("expense"))

        description  = request.form.get("description", "").strip()
        category     = request.form.get("category")
        note         = request.form.get("note", "").strip()
        is_recurring = bool(request.form.get("is_recurring"))

        if category == "Auto":
            category = ai_categorize(description)
            flash(f'AI categorized as: {category}', 'success')

        date_obj = parse_date(request.form.get("date")) or date.today()

        e = Expense(description=description, amount=amount, category=category,
                    date=date_obj, note=note, is_recurring=is_recurring,
                    user_id=current_user.id)
        db.session.add(e)
        db.session.commit()
        flash("Expense added", "success")
        return redirect(url_for("expense"))

    # GET request handles filtering and listing
    start_str        = (request.args.get("start") or "").strip()
    end_str          = (request.args.get("end") or "").strip()
    selected_category= (request.args.get("category") or "").strip()

    start_date = parse_date(start_str)
    end_date   = parse_date(end_str)

    q = Expense.query
    q = get_filtered_query(q, start_date, end_date, selected_category)
    expenses     = q.order_by(Expense.date.desc(), Expense.id.desc()).all()
    filter_total = round(sum(e.amount for e in expenses), 2)

    return render_template("expense.html",
        categories=CATEGORIES,
        today=date.today().isoformat(),
        expenses=expenses,
        filter_total=filter_total,
        start_str=start_str,
        end_str=end_str,
        selected_category=selected_category,
    )

@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    e = db.session.get(Expense, id)
    if e and e.user_id == current_user.id:
        db.session.delete(e)
        db.session.commit()
        flash('Deleted successfully', 'success')
    else:
        flash('Unauthorized', 'error')
    return redirect(url_for("expense"))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    e = db.session.get(Expense, id)
    if not e or e.user_id != current_user.id:
        return redirect(url_for('expense'))

    if request.method == 'POST':
        try:
            amount = float(request.form.get("amount", 0))
            if amount <= 0: raise ValueError
        except ValueError:
            flash("Invalid amount", "error")
            return redirect(url_for('edit', id=id))

        e.description  = request.form.get("description", "").strip()
        e.amount       = amount
        e.category     = request.form.get("category")
        e.date         = parse_date(request.form.get("date")) or date.today()
        e.note         = request.form.get("note", "").strip()
        e.is_recurring = bool(request.form.get("is_recurring"))
        db.session.commit()
        flash("Updated successfully", "success")
        return redirect(url_for("expense"))


    return render_template("edit.html", expense=e, categories=CATEGORIES)

# ── EXPORTS ───────────────────────────────────────────────────────────────────
@app.route("/export.csv")
@login_required
def export_csv():
    q        = Expense.query
    q        = get_filtered_query(q, parse_date(request.args.get("start","")),
                                  parse_date(request.args.get("end","")),
                                  request.args.get("category","").strip())
    expenses = q.order_by(Expense.date).all()
    csv_data = "Date,Description,Category,Amount,Note,Recurring\n" + \
               "\n".join([f"{e.date},{e.description},{e.category},{e.amount:.2f},"
                          f"{e.note or ''},{'Yes' if e.is_recurring else 'No'}"
                          for e in expenses])
    return Response(csv_data, headers={"Content-Type": "text/csv",
                    "Content-Disposition": "attachment; filename=expenses.csv"})

@app.route("/export_pdf")
@login_required
def export_pdf():
    start = parse_date(request.args.get("start",""))
    end   = parse_date(request.args.get("end",""))
    cat   = request.args.get("category","").strip()
    q     = get_filtered_query(Expense.query, start, end, cat)
    expenses = q.order_by(Expense.date.desc()).all()
    total    = sum(e.amount for e in expenses)

    cat_data    = get_filtered_query(
        db.session.query(Expense.category, func.sum(Expense.amount)), start, end, cat
    ).group_by(Expense.category).all()
    labels      = [c for c, _ in cat_data]
    values      = [amount for _, amount in cat_data]
    chart_image = generate_chart_image(labels, values, "Expenses by Category")

    html = render_template("pdf_report.html", expenses=expenses, total=total,
                           chart_image=chart_image,
                           generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                           user=current_user)
    pdf_file = HTML(string=html).write_pdf()
    return Response(pdf_file, headers={"Content-Type": "application/pdf",
                    "Content-Disposition": "attachment; filename=expense_report.pdf"})

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        # First ever user becomes admin
        is_admin = User.query.count() == 0
        new_user = User(username=username, password_hash=hashed_pw, is_admin=is_admin)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash('Account created!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        flash('Incorrect username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        new_username    = request.form.get('username')
        current_password= request.form.get('current_password')
        new_password    = request.form.get('new_password')

        if new_username and new_username != current_user.username:
            if User.query.filter_by(username=new_username).first():
                flash('Username taken.', 'error')
            else:
                current_user.username = new_username
                db.session.commit()
                flash('Username updated!', 'success')

        if new_password:
            if not current_password or not check_password_hash(current_user.password_hash, current_password):
                flash('Incorrect current password.', 'error')
            else:
                current_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
                db.session.commit()
                flash('Password changed.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# ── BUDGET ────────────────────────────────────────────────────────────────────
@app.route("/budget", methods=['GET', 'POST'])
@login_required
def budget():
    if request.method == 'POST':
        category = request.form.get("category")
        limit    = float(request.form.get("limit"))
        existing = Budget.query.filter_by(user_id=current_user.id, category=category).first()
        if existing:
            existing.limit = limit
            flash(f"Budget updated for {category}", "success")
        else:
            db.session.add(Budget(category=category, limit=limit, user_id=current_user.id))
            flash(f"Budget set for {category}", "success")
        db.session.commit()
        return redirect(url_for('budget'))

    budgets     = Budget.query.filter_by(user_id=current_user.id).all()
    budget_data = []
    for b in budgets:
        spent = db.session.query(func.sum(Expense.amount)).filter(
            Expense.user_id == current_user.id,
            Expense.category == b.category,
            func.strftime('%Y-%m', Expense.date) == date.today().strftime('%Y-%m')
        ).scalar() or 0
        percent = round((spent / b.limit) * 100) if b.limit > 0 else 0
        budget_data.append({'id': b.id, 'category': b.category, 'limit': b.limit,
                            'spent': spent, 'percent': percent,
                            'width': min(percent, 100), 'is_over': percent > 100})
    return render_template("budget.html", budget_data=budget_data, categories=CATEGORIES)

@app.route('/delete_budget/<int:id>', methods=['POST'])
@login_required
def delete_budget(id):
    b = db.session.get(Budget, id)
    if b and b.user_id == current_user.id:
        db.session.delete(b)
        db.session.commit()
        flash("Budget deleted", "success")
    else:
        flash("Budget not found or unauthorized", "error")
    return redirect(url_for('budget'))


@app.route('/delete_income/<int:id>', methods=['POST'])
@login_required
def delete_income(id):
    inc = db.session.get(Income, id)
    if inc and inc.user_id == current_user.id:
        db.session.delete(inc)
        db.session.commit()
        flash("Income deleted", "success")
    else:
        flash("Entry not found or unauthorized", "error")
    return redirect(url_for("income"))

# ── SAVINGS GOALS ─────────────────────────────────────────────────────────────
@app.route("/goals", methods=['GET', 'POST'])
@login_required
def goals():
    if request.method == 'POST':
        action = request.form.get("action")

        if action == "add":
            try:
                target = float(request.form.get("target", 0))
                if target <= 0: raise ValueError
            except ValueError:
                flash("Invalid target amount", "error")
                return redirect(url_for("goals"))
            title    = request.form.get("title", "").strip()
            deadline = parse_date(request.form.get("deadline"))
            db.session.add(SavingsGoal(title=title, target=target,
                                       deadline=deadline, user_id=current_user.id))
            db.session.commit()
            flash(f"Goal '{title}' created!", "success")

        elif action == "deposit":
            goal_id = int(request.form.get("goal_id", 0))
            g = db.session.get(SavingsGoal, goal_id)
            if g and g.user_id == current_user.id:
                try:
                    amount = float(request.form.get("deposit_amount", 0))
                    if amount <= 0: raise ValueError
                except ValueError:
                    flash("Invalid deposit amount", "error")
                    return redirect(url_for("goals"))
                g.saved = min(g.saved + amount, g.target)
                db.session.commit()
                flash(f"Added Rs.{amount:.0f} to '{g.title}'", "success")

        elif action == "delete":
            goal_id = int(request.form.get("goal_id", 0))
            g = db.session.get(SavingsGoal, goal_id)
            if g and g.user_id == current_user.id:
                db.session.delete(g)
                db.session.commit()
                flash("Goal deleted", "success")

        return redirect(url_for("goals"))

    goals_list = SavingsGoal.query.filter_by(user_id=current_user.id).all()
    return render_template("goals.html", goals=goals_list, today=date.today().isoformat())

# ── ADMIN PANEL ───────────────────────────────────────────────────────────────
# ── SYSTEM ADMINISTRATION ─────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin_panel():
    # 1. Strict Security Check (Replaces the old abort(403) logic)
    if current_user.username != 'admin':
        flash("Access Denied: You do not have admin privileges.", "error")
        return redirect(url_for('index'))

    # 2. Gather Platform Statistics
    total_users = User.query.count()
    total_expenses = db.session.query(func.sum(Expense.amount)).scalar() or 0
    total_incomes = db.session.query(func.sum(Income.amount)).scalar() or 0

    # 3. Gather Individual User Stats
    users = User.query.all()
    stats = []
    for u in users:
        exp_total = db.session.query(func.sum(Expense.amount)).filter_by(user_id=u.id).scalar() or 0
        inc_total = db.session.query(func.sum(Income.amount)).filter_by(user_id=u.id).scalar() or 0
        exp_count = Expense.query.filter_by(user_id=u.id).count()
        
        stats.append({
            'user': u,
            'exp_total': exp_total,
            'inc_total': inc_total,
            'net': inc_total - exp_total,
            'exp_count': exp_count
        })

    return render_template("admin.html", 
        total_users=total_users,
        total_expenses=total_expenses,
        total_incomes=total_incomes,
        stats=stats
    )

@app.route('/admin/delete_user/<int:id>', methods=['POST'])
@login_required
def admin_delete_user(id):
    # Strict Security Check
    if current_user.username != 'admin':
        flash("Access Denied.", "error")
        return redirect(url_for('index'))

    user_to_delete = db.session.get(User, id)
    if user_to_delete and user_to_delete.username != 'admin':
        # Delete all expenses and income associated with the user first
        Expense.query.filter_by(user_id=user_to_delete.id).delete()
        Income.query.filter_by(user_id=user_to_delete.id).delete()
        
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"User {user_to_delete.username} and all their data deleted.", "success")
    else:
        flash("Cannot delete the master admin account.", "error")
        
    return redirect(url_for('admin_panel'))

# ── REST API ──────────────────────────────────────────────────────────────────
@app.route("/api/summary")
@login_required
def api_summary():
    """Returns a JSON summary of the current user's finances."""
    today           = date.today()
    month_start     = date(today.year, today.month, 1)

    total_expense   = db.session.query(func.sum(Expense.amount))\
                                .filter(Expense.user_id == current_user.id).scalar() or 0
    total_income    = db.session.query(func.sum(Income.amount))\
                                .filter(Income.user_id == current_user.id).scalar() or 0
    this_month_exp  = db.session.query(func.sum(Expense.amount)).filter(
                        Expense.user_id == current_user.id,
                        Expense.date >= month_start).scalar() or 0
    this_month_inc  = db.session.query(func.sum(Income.amount)).filter(
                        Income.user_id == current_user.id,
                        Income.date >= month_start).scalar() or 0

    cat_breakdown = db.session.query(Expense.category, func.sum(Expense.amount))\
                              .filter(Expense.user_id == current_user.id)\
                              .group_by(Expense.category).all()

    return jsonify({
        "user"         : current_user.username,
        "generated_at" : datetime.now().isoformat(),
        "lifetime": {
            "total_expense": round(total_expense, 2),
            "total_income" : round(total_income, 2),
            "net_balance"  : round(total_income - total_expense, 2),
        },
        "this_month": {
            "expense": round(this_month_exp, 2),
            "income" : round(this_month_inc, 2),
        },
        "category_breakdown": {cat: round(float(amt), 2)
                                for cat, amt in cat_breakdown}
    })

@app.route("/api/expenses")
@login_required
def api_expenses():
    """Returns a paginated JSON list of the current user's expenses."""
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    category = request.args.get("category", "")

    q = Expense.query.filter_by(user_id=current_user.id)
    if category:
        q = q.filter_by(category=category)
    q = q.order_by(Expense.date.desc())

    try:
        paginated = q.paginate(page=page, per_page=per_page, error_out=False)
    except TypeError:
        paginated = q.paginate(page, per_page, False)

    return jsonify({
        "page"      : paginated.page,
        "per_page"  : paginated.per_page,
        "total"     : paginated.total,
        "pages"     : paginated.pages,
        "expenses"  : [{
            "id"          : e.id,
            "description" : e.description,
            "amount"      : e.amount,
            "category"    : e.category,
            "date"        : e.date.isoformat(),
            "note"        : e.note or "",
            "is_recurring": e.is_recurring,
        } for e in paginated.items]
    })

@app.route("/api/incomes")
@login_required
def api_incomes():
    """Returns a JSON list of the current user's income entries."""
    incomes = Income.query.filter_by(user_id=current_user.id)\
                         .order_by(Income.date.desc()).all()
    return jsonify({
        "total_income": round(sum(i.amount for i in incomes), 2),
        "incomes": [{
            "id"         : i.id,
            "description": i.description,
            "amount"     : i.amount,
            "source"     : i.source,
            "date"       : i.date.isoformat(),
        } for i in incomes]
    })

if __name__ == "__main__":
    app.run(debug=True)