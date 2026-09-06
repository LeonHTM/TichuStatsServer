import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required

from extensions import db, socketio
from logic.profileLogic import Profile
from logic.passkeyLogic import Credential, WebAuthnChallenge
from logic.gameLogic import EloHistory
from routes.auth_routes import app_token_required
from config import RP_ID, RP_NAME, ORIGIN

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import parse_authentication_credential_json, parse_registration_credential_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

passkey_bp = Blueprint("passkey", __name__, url_prefix="/passkey")

CHALLENGE_TTL_SECONDS = 120
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Mirrors client side fuck
NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


def _valid_name(name: str) -> bool:
    #return bool(NAME_RE.match(name)) and name.strip().lower() != "guest"
    return name != "guest"


def _name_taken(name: str) -> bool:
    return Profile.query.filter(db.func.lower(Profile.name) == name.lower()).first() is not None


# Stable opaque WebAuthn user handle for a profile that already exists 
def _webauthn_user_id(profile_id: int) -> bytes:
    return profile_id.to_bytes(8, "big")


def _save_challenge(challenge_id: str, profile_id: int | None, challenge: bytes, ceremony_type: str):
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    db.session.add(
        WebAuthnChallenge(
            challenge_id=challenge_id,
            profile_id=profile_id,
            challenge=challenge,
            ceremony_type=ceremony_type,
            expires_at=expires_at,
        )
    )
    db.session.commit()


def _pop_challenge(challenge_id: str, ceremony_type: str):
    row = WebAuthnChallenge.query.filter_by(
        challenge_id=challenge_id, ceremony_type=ceremony_type
    ).first()
    if row is None:
        return None
    profile_id, challenge, expires_at = row.profile_id, row.challenge, row.expires_at
    db.session.delete(row)
    db.session.commit()

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return profile_id, challenge



@passkey_bp.post("/register/options")
@app_token_required
def register_options():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not _valid_name(name):
        return jsonify({"error": "invalid_name"}), 400
    if _name_taken(name):
        return jsonify({"error": "name_taken"}), 409

    # Random opaque WebAuthn user handle — unrelated to the eventual
    # profile.id, just needs to be unique per registration ceremony.
    user_handle = uuid.uuid4().bytes

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=user_handle,
        user_name=name,
        user_display_name=name,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[],
    )

    challenge_id = str(uuid.uuid4())
    _save_challenge(challenge_id, None, options.challenge, "registration")

    body = json.loads(options_to_json(options))
    body["challengeId"] = challenge_id
    return jsonify(body)


@passkey_bp.post("/register/verify")
@app_token_required
def register_verify():
    data = request.get_json(silent=True) or {}
    challenge_id = data.get("challengeId")
    credential = data.get("credential")
    name = (data.get("name") or "").strip()
    if not challenge_id or not credential or not name:
        return jsonify({"error": "invalid_request"}), 400
    if not _valid_name(name):
        return jsonify({"error": "invalid_name"}), 400

    popped = _pop_challenge(challenge_id, "registration")
    if popped is None:
        return jsonify({"error": "challenge_expired"}), 400
    _profile_id, expected_challenge = popped

    # Re-check availability right before creating the account — the
    #client checked earlier, but time has passed during the Face ID prompt.
    if _name_taken(name):
        return jsonify({"error": "name_taken"}), 409

    try:
        parsed_credential = parse_registration_credential_json(json.dumps(credential))
        verification = verify_registration_response(
            credential=parsed_credential,
            expected_challenge=expected_challenge,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            require_user_verification=True,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "verification_failed", "detail": str(exc)}), 400

    transports = credential.get("transports")

    profile = Profile(email=None, name=name, date_added=datetime.utcnow())
    db.session.add(profile)
    db.session.flush()  # need profile.id before commit

    db.session.add(
        Credential(
            profile_id=profile.id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=",".join(transports) if transports else None,
        )
    )
    db.session.add(EloHistory(profile_id=profile.id, game_id=None, elo_change=0))
    db.session.commit()

    socketio.emit("profile_created", {"id": profile.id, "email": None, "name": profile.name})

    token = create_access_token(identity=str(profile.id))
    return jsonify({"token": token, "id": profile.id})


# Add a passkey to an already logged-in account (e.g. one made by email).
# Real user JWT, not the app token — this is a settings action. Existing
# credentials get excluded so the same authenticator can't register twice.
@passkey_bp.post("/add/options")
@jwt_required()
def add_options():
    profile = Profile.query.get(int(get_jwt_identity()))
    if profile is None:
        return jsonify({"error": "unknown_user"}), 404

    existing = Credential.query.filter_by(profile_id=profile.id).all()
    exclude_credentials = [PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=_webauthn_user_id(profile.id),
        user_name=profile.name or f"player-{profile.id}",
        user_display_name=profile.name or f"Player {profile.id}",
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude_credentials,
    )

    challenge_id = str(uuid.uuid4())
    _save_challenge(challenge_id, profile.id, options.challenge, "registration")

    body = json.loads(options_to_json(options))
    body["challengeId"] = challenge_id
    return jsonify(body)


@passkey_bp.post("/add/verify")
@jwt_required()
def add_verify():
    profile_id = int(get_jwt_identity())

    data = request.get_json(silent=True) or {}
    challenge_id = data.get("challengeId")
    credential = data.get("credential")
    if not challenge_id or not credential:
        return jsonify({"error": "invalid_request"}), 400

    popped = _pop_challenge(challenge_id, "registration")
    if popped is None:
        return jsonify({"error": "challenge_expired"}), 400
    stored_profile_id, expected_challenge = popped

    # Challenge must have been minted for THIS logged-in profile — stops
    # finishing a ceremony against a different account than it started on.
    if stored_profile_id != profile_id:
        return jsonify({"error": "challenge_mismatch"}), 400

    try:
        parsed_credential = parse_registration_credential_json(json.dumps(credential))
        verification = verify_registration_response(
            credential=parsed_credential,
            expected_challenge=expected_challenge,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            require_user_verification=True,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "verification_failed", "detail": str(exc)}), 400

    transports = credential.get("transports")
    new_credential = Credential(
        profile_id=profile_id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transports=",".join(transports) if transports else None,
    )
    db.session.add(new_credential)
    db.session.commit()

    return jsonify({"success": True, "credential": new_credential.to_dict()})


# Connecting an email to an existing account
@passkey_bp.patch("/connect_email")
@jwt_required()
def connect_email():
    profile = Profile.query.get(int(get_jwt_identity()))
    if profile is None:
        return jsonify({"error": "unknown_user"}), 404

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify({"error": "invalid_email"}), 400

    existing = Profile.query.filter_by(email=email).first()
    if existing and existing.id != profile.id:
        return jsonify({"error": "email_in_use"}), 409

    profile.email = email
    db.session.commit()
    socketio.emit("username_updated", {"profile_id": profile.id, "name": profile.name})
    return jsonify(profile.to_dict())


@passkey_bp.post("/login/options")
@app_token_required
def login_options():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower() or None

    allow_credentials = None
    profile_id_for_challenge = None
    if email:
        profile = Profile.query.filter_by(email=email).first()
        if profile:
            profile_id_for_challenge = profile.id
            creds = Credential.query.filter_by(profile_id=profile.id).all()
            allow_credentials = [PublicKeyCredentialDescriptor(id=c.credential_id) for c in creds]

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    challenge_id = str(uuid.uuid4())
    _save_challenge(challenge_id, profile_id_for_challenge, options.challenge, "authentication")

    body = json.loads(options_to_json(options))
    body["challengeId"] = challenge_id
    return jsonify(body)


@passkey_bp.post("/login/verify")
@app_token_required
def login_verify():
    data = request.get_json(silent=True) or {}
    challenge_id = data.get("challengeId")
    credential = data.get("credential")
    if not challenge_id or not credential:
        return jsonify({"error": "invalid_request"}), 400

    popped = _pop_challenge(challenge_id, "authentication")
    if popped is None:
        return jsonify({"error": "challenge_expired"}), 400
    _profile_id, expected_challenge = popped

    try:
        parsed_credential = parse_authentication_credential_json(json.dumps(credential))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "invalid_credential", "detail": str(exc)}), 400

    stored = Credential.query.filter_by(credential_id=parsed_credential.raw_id).first()
    if stored is None:
        return jsonify({"error": "unknown_credential"}), 400

    try:
        verification = verify_authentication_response(
            credential=parsed_credential,
            expected_challenge=expected_challenge,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "verification_failed", "detail": str(exc)}), 400

    stored.sign_count = verification.new_sign_count
    stored.last_used_at = datetime.utcnow()
    db.session.commit()

    profile = Profile.query.get(stored.profile_id)
    token = create_access_token(identity=str(profile.id))
    return jsonify({"token": token, "id": profile.id})



@passkey_bp.get("/credentials")
@jwt_required()
def list_credentials():
    profile_id = int(get_jwt_identity())
    creds = Credential.query.filter_by(profile_id=profile_id).all()
    return jsonify([c.to_dict() for c in creds])


@passkey_bp.delete("/credentials/<int:credential_id>")
@jwt_required()
def delete_credential(credential_id):
    profile_id = int(get_jwt_identity())
    cred = Credential.query.filter_by(id=credential_id, profile_id=profile_id).first()
    if cred is None:
        return jsonify({"error": "not_found"}), 404
    db.session.delete(cred)
    db.session.commit()
    return jsonify({"success": True})