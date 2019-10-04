from flask import Flask, flash, redirect, render_template, render_template_string, request, session, url_for, jsonify, make_response
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from functools import wraps
from tempfile import gettempdir
from urllib.parse import urlparse
import json
import passlib.pwd as pwd
import sqlalchemy
import os
import psycopg2

import time

app = Flask(__name__)

url = urlparse(os.environ["DATABASE_URL"])
conn = psycopg2.connect(database = url.path[1:],
                        user     = url.username,
                        password = url.password,
                        host     = url.hostname,
                        port     = url.port)

class SQL(object):
    """Wrap SQLAlchemy to provide a simple SQL API."""

    def __init__(self, url):
        """
        Create instance of sqlalchemy.engine.Engine.

        URL should be a string that indicates database dialect and connection arguments.

        http://docs.sqlalchemy.org/en/latest/core/engines.html#sqlalchemy.create_engine
        """
        try:
            self.engine = sqlalchemy.create_engine(url)
        except Exception as e:
            raise RuntimeError(e)

    def execute(self, text, *multiparams, **params):
        """
        Execute a SQL statement.
        """
        try:

            # bind parameters before statement reaches database, so that bound parameters appear in exceptions
            # http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.expression.text
            # https://groups.google.com/forum/#!topic/sqlalchemy/FfLwKT1yQlg
            # http://docs.sqlalchemy.org/en/latest/core/connections.html#sqlalchemy.engine.Engine.execute
            # http://docs.sqlalchemy.org/en/latest/faq/sqlexpressions.html#how-do-i-render-sql-expressions-as-strings-possibly-with-bound-parameters-inlined
            statement = sqlalchemy.text(text).bindparams(*multiparams, **params)
            result = self.engine.execute(str(statement.compile(compile_kwargs={"literal_binds": True})))

            # if SELECT (or INSERT with RETURNING), return result set as list of dict objects
            if result.returns_rows:
                rows = result.fetchall()
                return [dict(row) for row in rows]

            # if INSERT, return primary key value for a newly inserted row
            elif result.lastrowid is not None:
                return result.lastrowid

            # if DELETE or UPDATE (or INSERT without RETURNING), return number of rows matched
            else:
                return result.rowcount

        # if constraint violated, return None
        except sqlalchemy.exc.IntegrityError:
            return None

        # else raise error
        except Exception as e:
            raise RuntimeError(e)



db = SQL(os.environ["DATABASE_URL"])

app.config["SESSION_FILE_DIR"] = gettempdir()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


def login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/0.11/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login", next=request.url))
        
        return f(*args, **kwargs)
    return decorated_function
    
def aux_login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/0.11/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))        
        return f(*args, **kwargs)
    return decorated_function



@app.route("/login", methods=["GET", "POST"])
def login(message=""):
    if request.method == "POST":
        if not request.form.get("username"):
            return render_template("login.html", message = "Username required.")
        elif not request.form.get("password"):
            return render_template("login.html", message = "Password required.")
        
        ver = db.execute("SELECT * FROM trainers WHERE username = :username", username = request.form.get("username"))
        if len(ver) != 1 or not pwd_context.verify(request.form.get("password"), ver[0]["hash"]):
            return render_template("login.html", message = "Incorrect password or nonexistant Username")
        
        else:
            session["user_id"] = ver[0]["id"]
            return redirect(url_for("index"))      
    else:
        return render_template("login.html")

    
@app.route("/logout")
def logout():
    
    session.clear()

    return redirect(url_for("login"))


@app.route("/", methods = ['GET','POST'])
@aux_login_required
def index(message=""):

    schedule = db.execute("SELECT bookings.id, bookings.date, bookings.notes, bookings.private, bookings.location, bookings.delcode, courses.name AS coursename FROM bookings INNER JOIN courses ON bookings.course=courses.id WHERE trainer = :trainerid AND cast(date as date) > CURRENT_DATE ORDER BY bookings.date",
                          trainerid = session["user_id"])
    for row in schedule:
        delcount = db.execute("SELECT COUNT(id) AS delcount FROM delegates WHERE bookingid = :bookingid",
                              bookingid = row["id"])
        row.update({"delcount": delcount[0]["delcount"]})
        has_pcqs = db.execute("select exists(select 1 from pcq where bookingid=:bookingid)",
                              bookingid = row["id"])
        row.update({"has_pcqs": has_pcqs[0]["exists"]})

    return render_template("index.html", schedule = schedule)
    
@app.route("/pcq", methods = ['GET']) 
@login_required
def pcq(message=""):
    if request.args.get("key") != None:
        booking = db.execute("SELECT bookings.date, courses.name AS course FROM bookings INNER JOIN courses on bookings.course = courses.id WHERE bookings.id = :bookingid",
                                bookingid = request.args.get("key")
                                )
        pcqs = db.execute("SELECT * FROM pcq WHERE bookingid = :bookingid",
                                bookingid = request.args.get("key")
                                )
        return render_template("trainerinfo.html", pcqs = pcqs, booking = booking[0])
    else:
        return "Fail"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port,debug=True)
