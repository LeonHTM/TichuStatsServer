from flask_sqlalchemy import SQLAlchemy
from extensions import db, socketio
from logic.roundLogic import Round


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    email = db.Column(db.String(255), unique=True, nullable=True)
    name = db.Column(db.String(255), nullable=True)

    email_verified = db.Column(db.Boolean, nullable=False, default=False)

    profile_image_url = db.Column(db.String(500), nullable=True)

    date_added = db.Column(db.DateTime, nullable=True)

    elo = db.Column(db.Float, default=1000.0)

    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    device_tokens = db.relationship("UserDeviceToken", back_populates="profile", cascade="all, delete-orphan")
    stats = db.relationship("ProfileStats", back_populates="profile", cascade="all, delete-orphan")

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "profile_image_url": self.profile_image_url,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "elo": self.elo,
            "is_admin": self.is_admin,
        }

    def to_dict_simple(self):
        return {
            "id": self.id,
            "name": self.name,
            "profile_image_url": self.profile_image_url,
            "elo": self.elo,
            "is_admin": self.is_admin,
        }

    def to_dict_stats(self, timeframe="all_time"):
        stats = ProfileStats.query.filter_by(profile_id=self.id, timeframe=timeframe).first()
        base = {
            "id": self.id,
            "name": self.name,
            "elo": self.elo,
            "is_admin": self.is_admin,
        }
        if stats:
            base.update(stats.to_dict())
        return base

class ProfileSettings(db.Model):
    __tablename__ = "profile_settings"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    default_target = db.Column(db.Integer, nullable=False, default=1000)
    show_pingu     = db.Column(db.Boolean, nullable=False, default=True)
    drag_mode      = db.Column(db.Boolean, nullable=False, default=False)
    show_all_players = db.Column(db.Boolean, nullable=False, default=False)
    sort_by_profile = db.Column("sortByProfile", db.Integer, nullable=False, default=0)
    sort_by_stats   = db.Column("sortByStats", db.Integer, nullable=False, default=2)

    def to_dict(self):
        return {
            "user_id":          self.user_id,
            "default_target":   self.default_target,
            "show_pingu":       self.show_pingu,
            "drag_mode":        self.drag_mode,
            "show_all_players": self.show_all_players,
            "sort_by_profiles": self.sort_by_profile,
            "sort_by_stats":    self.sort_by_stats,
        }



class ProfileStats(db.Model):
    __tablename__ = "profile_stats"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    timeframe = db.Column(db.Enum("all_time", "year", "month", "week", "day"), nullable=False)
    calculated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    winner_percentage = db.Column(db.Float, default=0)
    tichu_master = db.Column(db.Float, default=0)
    visionary = db.Column(db.Float, default=0)
    addict = db.Column(db.Float, default=0)
    teamplayer = db.Column(db.Float, default=0)
    announcer = db.Column(db.Float, default=0)
    saboteur = db.Column(db.Float, default=0)
    gambler = db.Column(db.Float, default=0)
    big_gambler = db.Column(db.Float, default=0)
    pingu_gambler = db.Column(db.Float, default=0)
    bomber = db.Column(db.Float, default=0)

    profile = db.relationship("Profile", back_populates="stats")

    __table_args__ = (
        db.UniqueConstraint("profile_id", "timeframe", name="unique_profile_timeframe"),
    )

    def to_dict(self):
        return {
            "timeframe": self.timeframe,
            "calculated_at": self.calculated_at.isoformat() if self.calculated_at else None,
            "winner_percentage": self.winner_percentage,
            "tichu_master": self.tichu_master,
            "visionary": self.visionary,
            "addict": self.addict,
            "teamplayer": self.teamplayer,
            "announcer": self.announcer,
            "saboteur": self.saboteur,
            "gambler": self.gambler,
            "big_gambler": self.big_gambler,
            "pingu_gambler": self.pingu_gambler,
            "bomber": self.bomber,
        }


class ProfileFriend(db.Model):
    __tablename__ = "profile_friends"

    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), primary_key=True)
    friend_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), primary_key=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class FriendRequest(db.Model):
    __tablename__ = "friend_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    status = db.Column(db.Enum("pending", "accepted", "rejected"), default="pending")
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class UserDeviceToken(db.Model):
    __tablename__ = "user_device_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    device_token = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    profile = db.relationship("Profile", back_populates="device_tokens")


from datetime import datetime, timedelta
import time

#Calculate Stats for user and given Timeframe
def calculateStats(user_id, timeframe="all_time"):
    #KEEP THIS IMPORT INSIDE OR IT BREAKS IDK Y
    from logic.gameLogic import Game
    #How exact the calcalutions should be
    round_to = 4

    #To test how long calclaution took
    start = time.time()

    #User
    user = Profile.query.get(user_id)
    if not user:
        return
    uid = user_id

    #TimeFrames
    now = datetime.utcnow()
    if timeframe == "day":
        timeframe_delta = now - timedelta(days=1)
    elif timeframe == "week":
        timeframe_delta = now - timedelta(weeks=1)
    elif timeframe == "month":
        timeframe_delta = now - timedelta(days=30)
    elif timeframe == "year":
        timeframe_delta = now - timedelta(days=365)
    else:
        timeframe_delta = None  # all_time

    def get_team(game):
        if uid in (game.team1_player1_id, game.team1_player2_id):
            return 1
        return 2

    def get_opponents(game):
        if get_team(game) == 1:
            return (game.team2_player1_id, game.team2_player2_id)
        return (game.team1_player1_id, game.team1_player2_id)

    def get_bombs(round):
        return {
            round.first_profile_id: round.first_bombs,
            round.second_profile_id: round.second_bombs,
            round.third_profile_id: round.third_bombs,
            round.fourth_profile_id: round.fourth_bombs,
        }.get(uid, 0)

    #Take all the Games the user was part of
    games_query = Game.query.filter(
        db.or_(
            Game.team1_player1_id == uid,
            Game.team1_player2_id == uid,
            Game.team2_player1_id == uid,
            Game.team2_player2_id == uid,
        )
    )

    #Filter games to take only the one in timeframe
    if timeframe_delta:
        games_query = games_query.filter(Game.date >= timeframe_delta)

    all_games = games_query.all()
    finished_games = [g for g in all_games if g.winner is not None]
    #Also considers the Rounds of the Game you are in rn change ot finished_games if you want to take finsihed games
    game_ids = [g.id for g in all_games]
    game_map = {g.id: g for g in all_games}

    #Get all the Rounds of all the gammes
    rounds_query = Round.query.filter(
        Round.game_id.in_(game_ids),
        Round.bool_win_round == True,
        db.or_(
            Round.first_profile_id == uid,
            Round.second_profile_id == uid,
            Round.third_profile_id == uid,
            Round.fourth_profile_id == uid,
        )
    )
    #Take only Rounds in the timeframe
    if timeframe_delta:
        rounds_query = rounds_query.filter(Round.date >= timeframe_delta)

    all_rounds = rounds_query.all()

    #Addict number of (finsihed) Games played
    addict = len(finished_games)

    #Winner Percentage
    if finished_games:
        #Sum up all the Wins 
        won = sum(1 for g in finished_games if get_team(g) == g.winner)
        winner_percentage = round(won / len(finished_games), round_to) 
    else:
        winner_percentage = 0.0

    #Tichumaster: Annoucement Points from all Rounds 
    tichu_points_total = 0
    for r in all_rounds:
        if uid in (r.announced_tichu or []):
            tichu_points_total += 100 if r.first_profile_id == uid else -100
        elif uid in (r.announced_big_tichu or []):
            tichu_points_total += 200 if r.first_profile_id == uid else -200
        elif uid in (r.announced_pingu or []):
            tichu_points_total += 400 if r.first_profile_id == uid else -400

    tichu_master = round(tichu_points_total / len(all_rounds), round_to) if all_rounds else 0.0

   #Visionary: Percentage when you were first and announced a tichu
    rounds_first = [r for r in all_rounds if r.first_profile_id == uid]
    if rounds_first:
        #Sum up when you announced somthing
        announced_when_first = sum(
            1 for r in rounds_first
            if uid in (r.announced_tichu or [])
            or uid in (r.announced_big_tichu or [])
            or uid in (r.announced_pingu or [])
        )
        visionary = round(announced_when_first / len(rounds_first), round_to)
    else:
        visionary = 0.0

    #Teamplayer: Double Win rate
    if all_rounds:
        double_wins = sum(
            1 for r in all_rounds
            if (get_team(game_map[r.game_id]) == 1 and r.double_win_team1)
            or (get_team(game_map[r.game_id]) == 2 and r.double_win_team2)
        )
        teamplayer = round(double_wins / len(all_rounds), round_to)
    else:
        teamplayer = 0.0

    
    # Announcer: Percentage how often you announce something
    if all_rounds:
        announced_rounds = sum(
            1 for r in all_rounds
            if uid in (r.announced_tichu or [])
            or uid in (r.announced_big_tichu or [])
            or uid in (r.announced_pingu or [])
        )
        announcer = round(announced_rounds / len(all_rounds), round_to)
    else:
        announcer = 0.0

    #Saboteur: percentage how often you destroyed an oponents tichu
    opponent_announcements = 0
    opponent_failed = 0
    for r in all_rounds:
        game = game_map[r.game_id]
        opp1, opp2 = get_opponents(game)
        for opp in (opp1, opp2):
            if opp in (r.announced_tichu or []) or opp in (r.announced_big_tichu or []) or opp in (r.announced_pingu or []):
                opponent_announcements += 1
                if r.first_profile_id != opp:
                    opponent_failed += 1

    saboteur = round(opponent_failed / opponent_announcements, round_to) if opponent_announcements else 0.0

    #Gambler: Tichu success rate
    tichu_announced = [r for r in all_rounds if uid in (r.announced_tichu or [])]
    gambler = round(
        sum(1 for r in tichu_announced if r.first_profile_id == uid) / len(tichu_announced), round_to
    ) if tichu_announced else 0.0

    #Big Gambler: Big Tichu success rate
    big_tichu_announced = [r for r in all_rounds if uid in (r.announced_big_tichu or [])]
    big_gambler = round(
        sum(1 for r in big_tichu_announced if r.first_profile_id == uid) / len(big_tichu_announced), round_to
    ) if big_tichu_announced else 0.0

    #Pingu Gambler: Pingus success rate
    pingu_announced = [r for r in all_rounds if uid in (r.announced_pingu or [])]
    pingu_gambler = round(
        sum(1 for r in pingu_announced if r.first_profile_id == uid) / len(pingu_announced), round_to
    ) if pingu_announced else 0.0

    #Bomber: Bombs per round
    bomber = round(
        sum(get_bombs(r) for r in all_rounds) / len(all_rounds), round_to
    ) if all_rounds else 0.0

    #Save to database
    stats = ProfileStats.query.filter_by(profile_id=uid, timeframe=timeframe).first()
    if not stats:
        stats = ProfileStats(profile_id=uid, timeframe=timeframe)
        db.session.add(stats)

    stats.winner_percentage = winner_percentage
    stats.tichu_master      = tichu_master
    stats.visionary         = visionary
    stats.addict            = addict
    stats.teamplayer        = teamplayer
    stats.announcer         = announcer
    stats.saboteur          = saboteur
    stats.gambler           = gambler
    stats.big_gambler       = big_gambler
    stats.pingu_gambler     = pingu_gambler
    stats.bomber            = bomber

    db.session.commit()
    #To measure how long calcuation took pt.2 
    elapsed = time.time() - start
    #print(f"calculateStats({user_id}, {timeframe}) took {elapsed:.3f}s }")