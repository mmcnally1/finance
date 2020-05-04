import os
import re

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from pytz import timezone

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("postgres://sdijddgwnaakcw:f6c699db56ed61c4a4aa2316ff8b17d2c6441a957909ef1acf3323c7f3c5f787@ec2-18-215-99-63.compute-1.amazonaws.com:5432/d6gplio39d979l
")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session["user_id"]

    # Get live quote for up to date portfolio values, use to calculate total value
    symb = []
    shares = []
    live_quote = []
    live_price = []
    total_price = []
    total_holdings = 0
    acct = db.execute("SELECT * FROM holdings WHERE user_id = ?", user_id)
    for i in range(len(acct)):
        symb.append(acct[i]["symbol"])
        shares.append(acct[i]["shares"])
        live_quote.append(lookup(symb[i]))
        live_price.append(live_quote[i]["price"])
        t = usd(shares[i] * live_price[i])
        total_price.append(t)
        total_holdings = usd(total_holdings + t)
        db.execute("UPDATE holdings SET cur_price = ?, total = ? WHERE user_id = ? and symbol = ?", live_price[i], total_price[i], user_id, symb[i])
    c = db.execute("SELECT * from users WHERE id = ?", user_id)
    cash = usd(c[0]["cash"])
    acct_total = usd(total_holdings + cash)
    return render_template("index.html", acct = acct, total_holdings = total_holdings, cash = cash, acct_total = acct_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")
    else:
        # Ensure valid symbol and number of shares entered
        if not request.form.get("symbol"):
            return apology("please enter a valid symbol", 403)
        if not request.form.get("shares"):
            return apology("please enter the number of shares you wish to purchase", 403)
        try:
            shares = int(request.form.get("shares"))
        except:
            return apology("please enter a valid number of shares", 403)
        if not shares > 0:
            return apology("you must purchase at least 1 share", 403)
        symbol = request.form.get("symbol")
        stock = lookup(symbol)
        if stock == None:
            return apology("please enter a valid symbol", 403)
        else:
            price = usd(stock["price"])
            total_price = usd(price * shares)
            user_id = session["user_id"]
            dt = datetime.now()
            timestamp = dt.astimezone(timezone('US/Central'))
            row_cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)
            start_cash = usd(row_cash[0]["cash"])
            new_cash = usd(start_cash - total_price)

            # Ensure cash balance is sufficient
            if new_cash < 0:
                return apology ("you do not have enough cash to complete this purchase", 403)
            buy = "Buy"

            # Insert purchase information into "history"
            db.execute("INSERT INTO history (user_id, trans_type, symbol, price, shares, date_time) VALUES (:user_id, :trans_type, :symbol, :price, :shares, :date_time)",
                        user_id = user_id, trans_type = buy, symbol = symbol, price = price, shares = shares, date_time = timestamp)

            # Update cash balance
            db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash, user_id)
            owned = db.execute("SELECT * FROM holdings WHERE user_id = ? and symbol = ?", user_id, symbol)

            # Create new row in holdings if user doesn't currently own shares of stock
            if len(owned) == 0:
                db.execute("INSERT INTO holdings (user_id, symbol, shares, purch_price, total) VALUES (:user_id, :symbol, :shares, :purch_price, :total)",
                            user_id = user_id, symbol = symbol, shares = shares, purch_price = price, total = total_price)

            # Update holding if user already owns shares of stock
            else:
                prev_shares = owned[0]["shares"]
                prev_total = usd(owned[0]["total"])
                new_shares = shares + prev_shares
                new_total = usd(prev_total + total_price)
                new_price = usd(new_total / new_shares)
                db.execute("UPDATE holdings SET shares = ?, purch_price = ?, total = ? WHERE user_id = ? and symbol = ?",
                            new_shares, new_price, new_total, user_id, symbol)

            return render_template("bought.html", start_balance = usd(start_cash), company = symbol, price = usd(price), shares = shares, total_price = usd(total_price), new_balance = usd(new_cash))




@app.route("/history")
@login_required
def history():
    """Show 20 most recent transactions"""
    user_id = session["user_id"]
    hist = db.execute("SELECT * FROM history WHERE user_id = ? ORDER BY date_time desc LIMIT 20", user_id)
    return render_template("history.html", hist = hist)

@app.route("/history_all")
@login_required
def history_all():
    """Show full history of transactions"""
    user_id = session["user_id"]
    hist = db.execute("SELECT * FROM history WHERE user_id = ? ORDER BY date_time desc", user_id)
    return render_template("history_all.html", hist = hist)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    else:

        # Ensure valid symbol entered
        if not request.form.get("symbol"):
            return apology("please enter a valid ticker symbol", 403)
        ticker = request.form.get("symbol")
        if lookup(ticker) == None:
            return apology("please enter a valid ticker symbol", 403)
        else:

            # Display requested quote
            stock = lookup(ticker)
            return render_template("quoted.html", company = stock["name"], price = usd(stock["price"]), symbol = stock["symbol"])


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register User"""
    if request.method == "GET":
        return render_template("register.html")
    else:
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        #Ensure password confirmation was submitted
        elif not request.form.get("confirmation"):
            return apology("passwords must match", 403)

        # Ensure username is available
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))
        if len(rows) != 0:
            return apology("username taken, please choose a new username", 403)
        username = request.form.get("username")
        pw = request.form.get("password")
        conf =  request.form.get("confirmation")

        # Ensure passwords match
        if pw != conf:
            return apology("passwords must match", 403)

        # Ensure password length is 6-12 characters
        if len(pw) < 6 or len(pw) > 12:
            return apology("password must be between 6-12 characters and include a number and special character", 403)
        no_count = 0
        sc_count = 0

        # Ensure password contains at least 1 number
        for i in pw:
            if i.isdigit() == True:
                no_count = no_count + 1
        if no_count == 0:
            return apology("password must be between 6-12 characters and include a number and special character", 403)

        # Ensure password contains at least 1 special character
        regex = re.compile('[@_!#$%^&*()<>?/\|}{~:]')
        if (regex.search(pw) == None):
            return apology("password must be between 6-12 characters and include a number and special character", 403)

        # Insert user, hash into users table
        pw_hash = generate_password_hash(pw)
        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username = username, hash = pw_hash)
        return redirect("/")

@app.route("/password_change", methods=["GET", "POST"])
@login_required
def password_change():
    if request.method == "GET":
        return render_template("password_change.html")
    else:
        # Ensure password was submitted
        if not request.form.get("password"):
            return apology("must provide password", 403)

        #Ensure password confirmation was submitted
        if not request.form.get("confirmation"):
            return apology("passwords must match", 403)
        pw = request.form.get("password")
        conf =  request.form.get("confirmation")

        # Ensure passwords match
        if pw != conf:
            return apology("passwords must match", 403)

        # Ensure password is 6-12 characters
        if len(pw) < 6 or len(pw) > 12:
            return apology("password must be between 6-12 characters and include a number", 403)
        no_count = 0
        sc_count = 0

        # Ensure password contains at least 1 number
        for i in pw:
            if i.isdigit() == True:
                no_count = no_count + 1
        if no_count == 0:
            return apology("password must be between 6-12 characters and include a number and special character", 403)

        # Ensure password contains at least 1 special character
        regex = re.compile('[@_!#$%^&*()<>?/\|}{~:]')
        if (regex.search(pw) == None):
            return apology("password must be between 6-12 characters and include a number and special character", 403)

        # Update password in users table
        pw_hash = generate_password_hash(pw)
        user_id = session["user_id"]
        db.execute("UPDATE users SET hash = ? WHERE id = ?", pw_hash, user_id)
        return redirect("/")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":

        # Display user's holdings in drop-down menu
        user_id = session["user_id"]
        sales = db.execute("SELECT symbol FROM holdings WHERE user_id = ?", user_id)
        return render_template("sell.html", sales = sales)
    else:

        # Ensure valid symbol, number of shares
        if not request.form.get("symbol"):
            return apology("please select a valid symbol", 403)

        if not request.form.get("shares"):
            return apology("please enter the number of shares you wish to sell", 403)
        shares = int(request.form.get("shares"))

        if not shares > 0:
            return apology("please enter a valid number of shares to sell", 403)

        # Ensure user owns stock to be sold
        user_id = session["user_id"]
        symbol = request.form.get("symbol")
        stock = db.execute("SELECT * from holdings WHERE user_id = ? and symbol = ?", user_id, symbol)
        if len(stock) == 0:
            return apology("you do not own the selected stock", 403)
        shares_owned = stock[0]["shares"]
        prev_total = usd(stock[0]["total"])
        cur_stock = lookup(symbol)
        cur_price = usd(cur_stock["price"])

        # Ensure user owns number of shares to be sold
        if shares > shares_owned:
            return apology("the number of shares entered exceeds the number of shares in your account", 403)

        new_shares = shares_owned - shares
        amt_sold = usd(shares * cur_price)
        new_total = usd(prev_total - amt_sold)
        sell = "Sell"
        timestamp = datetime.now()
        row_cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)
        start_cash = usd(row_cash[0]["cash"])
        new_cash = usd(start_cash + amt_sold)

        # Delete row from database if sale liquidates user's entire position in stock
        if new_shares == 0:
            db.execute("INSERT INTO history (user_id, trans_type, symbol, price, shares, date_time) VALUES (:user_id, :trans_type, :symbol, :price, :shares, :date_time)",
                        user_id = user_id, trans_type = sell, symbol = symbol, price = cur_price, shares = shares, date_time = timestamp)
            db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash, user_id)
            db.execute("DELETE from holdings WHERE user_id = ? and symbol = ?", user_id, symbol)
            return redirect("/")

        purch_price = usd(new_total / new_shares)

        # Insert transaction into "history"
        db.execute("INSERT INTO history (user_id, trans_type, symbol, price, shares, date_time) VALUES (:user_id, :trans_type, :symbol, :price, :shares, :date_time)",
                        user_id = user_id, trans_type = sell, symbol = symbol, price = cur_price, shares = shares, date_time = timestamp)

        # Update user's holdings
        db.execute("UPDATE holdings SET shares = ?, purch_price = ?, total = ? WHERE user_id = ? and symbol = ?",
                            new_shares, purch_price, new_total, user_id, symbol)

        # Update user's cash balance
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash, user_id)

        return render_template("sold.html", start_balance = start_cash, company = symbol, price = cur_price, shares = shares,
                                total_price = amt_sold, new_balance = new_cash)

@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    if request.method == "GET":
        return render_template("deposit.html")
    else:
        # Ensure amount to be deposited > 0 and < 10000
        if not request.form.get("deposit"):
            return apology("please enter an amount to deposit", 403)
        deposit = float(request.form.get("deposit"))
        if deposit < 0:
            return apology("must deposit a positive value", 403)
        if deposit > 10000:
            return apology("deposit limit $10,000", 403)
        user_id = session["user_id"]
        row = db.execute("SELECT * from users WHERE id = ?", user_id)
        cash = usd(row[0]["cash"])
        new_cash = usd(cash + deposit)

        # Add cash to user's balance
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash, user_id)
        dep = "Deposit"
        timestamp = datetime.now()
        symb = " "
        shares = " "

        # Insert deposit into "history"
        db.execute("INSERT INTO history (user_id, trans_type, symbol, price, shares, date_time) VALUES (:user_id, :trans_type, :symbol, :price, :shares, :date_time)",
                    user_id = user_id, trans_type = dep, symbol = symb, price = deposit, shares = shares, date_time = timestamp)
        return redirect("/")

def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
