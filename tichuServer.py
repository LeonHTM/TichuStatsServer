from flask import Flask, jsonify
from profileLogic import db, Profile
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME

tichuServer = Flask(__name__)

# MySQL config
tichuServer.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
)

tichuServer.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Connect db to app
db.init_app(tichuServer)


@tichuServer.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@tichuServer.route("/profiles", methods=["GET"])
def get_profiles():
    profiles = Profile.query.all()
    return jsonify([p.to_dict() for p in profiles])


if __name__ == "__main__":
    tichuServer.run(debug=True)