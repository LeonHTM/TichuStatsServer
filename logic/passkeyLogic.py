from extensions import db


class Credential(db.Model):
    __tablename__ = "credentials"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)

    credential_id = db.Column(db.LargeBinary(1024), nullable=False, unique=True)
    public_key = db.Column(db.LargeBinary(1024), nullable=False)
    sign_count = db.Column(db.BigInteger, nullable=False, default=0)
    transports = db.Column(db.String(255), nullable=True)
    nickname = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    last_used_at = db.Column(db.DateTime, nullable=True)

    profile = db.relationship(
        "Profile",
        backref=db.backref("credentials", cascade="all, delete-orphan"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "nickname": self.nickname,
            "transports": self.transports,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


class WebAuthnChallenge(db.Model):
    """Short-lived, single-use challenge for an in-flight registration or
    login ceremony."""

    __tablename__ = "webauthn_challenges"

    challenge_id = db.Column(db.String(36), primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True)
    challenge = db.Column(db.LargeBinary(255), nullable=False)
    ceremony_type = db.Column(db.Enum("registration", "authentication"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())