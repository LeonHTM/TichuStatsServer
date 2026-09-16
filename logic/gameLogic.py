from flask import jsonify
from flask_sqlalchemy import SQLAlchemy
from extensions import db, socketio
from logic.roundLogic import Round
from logic.profileLogic import Profile, calculateStats
from datetime import datetime

class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    target = db.Column(db.Integer, default=1000)
    allow_pingus = db.Column(db.Boolean, default=True)

    team1_player1_id = db.Column(db.Integer)
    team1_player2_id = db.Column(db.Integer)
    team2_player1_id = db.Column(db.Integer)
    team2_player2_id = db.Column(db.Integer)

    guest2_name = db.Column(db.String(255), nullable=True)
    guest3_name = db.Column(db.String(255), nullable=True)
    guest4_name = db.Column(db.String(255), nullable=True)

    current_points_team1 = db.Column(db.Integer, default=0)
    current_points_team2 = db.Column(db.Integer, default=0)

    winner = db.Column(db.Integer)
    rated = db.Column(db.Boolean, default=None, nullable=True)
    calculated = db.Column(db.Boolean, default=False)

    rounds = db.relationship("Round", back_populates="game", lazy=True, cascade="all, delete-orphan")

    #Validate Game
    def validate(self):
        players = [
            self.team1_player1_id,
            self.team1_player2_id,
            self.team2_player1_id,
            self.team2_player2_id
        ]

        if None in players:
            raise ValueError("All 4 players must be set")

        if len(set(players)) != 4:
            raise ValueError("Players must be unique")

        if self.target <= 0:
            raise ValueError("Invalid target value")

    # Game to Dictionary
    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,

            "target": self.target,
            "allow_pingus": self.allow_pingus,

            "team1_player1_id": self.team1_player1_id,
            "team1_player2_id": self.team1_player2_id,
            "team2_player1_id": self.team2_player1_id,
            "team2_player2_id": self.team2_player2_id,

            "guest2_name": self.guest2_name,
            "guest3_name": self.guest3_name,
            "guest4_name": self.guest4_name,

            "current_points_team1": self.current_points_team1,
            "current_points_team2": self.current_points_team2,

            "winner": self.winner,
            "rated": self.rated,
        }

#EloHistory Point to save change in Elo
class EloHistory(db.Model):
    __tablename__ = "elo_history"

    id         = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    game_id    = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"), nullable=True)
    elo_change = db.Column(db.Float, nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

#Recalculate the current Points for each Team in a Tichu Game
def recalculate(game_id,tie=False):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    rounds = (
        Round.query
        .filter_by(game_id=game_id)
        .order_by(Round.round_order)
        .all()
    )

    game.current_points_team1 = 0
    game.current_points_team2 = 0
    game.winner = None

    if tie : 
        for round in rounds:
                    game.current_points_team1 = game.current_points_team1 + round.round_points_team1 + round.tichu_points_team1
                    game.current_points_team2 = game.current_points_team2 + round.round_points_team2 + round.tichu_points_team2
        game.winner = 3
    else:


        def win_condition(current_points_team1, current_points_team2,target):
            return (current_points_team1 >= target and current_points_team1 > current_points_team2) or (current_points_team2 >= target and current_points_team2 > current_points_team1) 

        #Tracks if this is the final round of reaching the target
        reached_target = False

        for round in rounds:
            game.current_points_team1 = game.current_points_team1 + round.round_points_team1 + round.tichu_points_team1
            game.current_points_team2 = game.current_points_team2 + round.round_points_team2 + round.tichu_points_team2

            if not win_condition(game.current_points_team1, game.current_points_team2,game.target):
                round.bool_win_round = True
            else:
                if reached_target == False:
                    reached_target = True
                    round.bool_win_round = True
                    #When players choose tie the taget gets set to the poitns of the team with mroe poitns so
                    if game.current_points_team1 > game.current_points_team2:
                        game.winner = 1
                    elif game.current_points_team2 > game.current_points_team1:
                        game.winner = 2
                else:
                    round.bool_win_round = False
                    game.current_points_team1 = game.current_points_team1 - round.round_points_team1 - round.tichu_points_team1
                    game.current_points_team2 = game.current_points_team2 - round.round_points_team2 - round.tichu_points_team2
        

    playerIds = [game.team1_player1_id, game.team1_player2_id, game.team2_player1_id, game.team2_player2_id] 
  
 
    #calculateStats for all TimeFrames
    for playerId in playerIds:
            calculateStats(playerId, "all_time")
            calculateStats(playerId, "year")
            calculateStats(playerId, "month")
            calculateStats(playerId, "week")
            calculateStats(playerId, "day")

    db.session.commit()

    socketio.emit("game_recalculated", {"game_id": game_id})

    return jsonify({
        "game_id": game_id,
        "current_points_team1": game.current_points_team1,
        "current_points_team2": game.current_points_team2,
        "winner": game.winner,
    }), 200

#Finish Game: Elo gets calculated for all Players if no Guests are present
def finish_game(game_id,tie=False):
    game = Game.query.get(game_id)

    if not game:
        print("Could not finish game: Game Not found")
        return jsonify({"error": "Game not found"}), 404

    print("finish game")
    player_ids = [
        game.team1_player1_id,
        game.team1_player2_id,
        game.team2_player1_id,
        game.team2_player2_id
    ]

    if any(p in (-1, -2, -3, -4) for p in player_ids) or tie==True:
        game.rated = False
    else:
        game.rated = True

    db.session.commit()

    calculate_elo(game_id, game.winner)

# If a user gets deleted he gets replaced with a guest in active Games
def handle_user_deleted(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return None, 404

    #Ids of Guests
    ids = [-1, -2, -3, -4]

    #All Active Games
    active_games = Game.query.filter(
        Game.winner == None,
        db.or_(
            Game.team1_player1_id == profile_id,
            Game.team1_player2_id == profile_id,
            Game.team2_player1_id == profile_id,
            Game.team2_player2_id == profile_id,
        )
    ).all()

    
    for game in active_games:

        #Check which Players are already Guests
        existing_guests_in_game = set()
        for slot in [game.team1_player1_id, game.team1_player2_id,
                     game.team2_player1_id, game.team2_player2_id]:
            if slot is not None and slot in ids:  
                existing_guests_in_game.add(slot)
        #replacement is first guest that is not already in Game
        replacement_id = None
        for guest_id in ids:
            if guest_id not in existing_guests_in_game:
                replacement_id = guest_id
                break
        
        if replacement_id is None:
            return {"error": f"Cannot delete profile: active game {game.id} has no available guest slot."}, 409

        #Replace the deleted Profile wiht Guest
        if game.team1_player1_id == profile_id:
            game.team1_player1_id = replacement_id
        elif game.team1_player2_id == profile_id:
            game.team1_player2_id = replacement_id
        elif game.team2_player1_id == profile_id:
            game.team2_player1_id = replacement_id
        elif game.team2_player2_id == profile_id:
            game.team2_player2_id = replacement_id

        #If now are the Players are guest delete the Game
        if game.team1_player1_id < 0 and game.team1_player2_id < 0 and game.team2_player1_id < 0 and game.team2_player2_id < 0:
    
                #Delete Game
                db.session.delete(game)
                db.session.commit()
                socketio.emit("game_deleted", {"game_id": game.id})
                return jsonify({"success": True}), 200
        else:
            print(f"delete_profile: replaced profile {profile_id} with guest {replacement_id} in game {game.id}")
            socketio.emit("game_updated", game.to_dict())

    db.session.commit()
    return None, 200 
        
#Function to calculate elo for all TimeFrames and Profiles in Game
def calculate_elo(game_id, winner):
    winner1 = 0
    winner2 = 0

    if winner == 2:
        winner2 = 1
        winner1 = 0
    elif winner == 1:
        winner2 = 0
        winner1 = 1
    elif winner == 3:
        winner2 = 1
        winner1 = 1
    else:
        print("ERROR: No winner was given for Calculation")
        return

    game = Game.query.get(game_id)

    # Use filter_by().first() instead of .get() so negative IDs work correctly
    team1_player1 = Profile.query.filter_by(id=game.team1_player1_id).first()
    team1_player2 = Profile.query.filter_by(id=game.team1_player2_id).first()
    team2_player1 = Profile.query.filter_by(id=game.team2_player1_id).first()
    team2_player2 = Profile.query.filter_by(id=game.team2_player2_id).first()

    if any(p is None for p in [team1_player1, team1_player2, team2_player1, team2_player2]):
        print("ERROR: One or more players not found in DB")
        return

    # Guest Profiles used to have null Elo not the case anymore
    def safe_elo(profile):
        return profile.elo if profile.elo is not None else 1000

    # Calculate avg Elo rating of teams
    team1_elo = (safe_elo(team1_player1) + safe_elo(team1_player2)) / 2
    team2_elo = (safe_elo(team2_player1) + safe_elo(team2_player2)) / 2

    # Calculate expected win probability
    Exp1 = 1 / (1 + 10 ** ((team2_elo - team1_elo) / 400))
    Exp2 = 1 - Exp1

    #Points gets scaled by how big the Target was
    multiplier = (game.target / 1000) * 20
    delta1 = round(multiplier * (winner1 - Exp1), 2)
    delta2 = round(multiplier * (winner2 - Exp2), 2)


    if game.rated:
        # Only update elo and write history for real (positive ID) players
        for p, delta in [
            (team1_player1, delta1), (team1_player2, delta1),
            (team2_player1, delta2), (team2_player2, delta2)
        ]:
            if p.id > 0:
                p.elo = safe_elo(p) + delta
                db.session.add(EloHistory(profile_id=p.id, game_id=game_id, elo_change=delta,changed_at=game.date))
    else:
        # Add ELoHistory Points for Users (will show up as line in Graph), do nothing for Guests
        for p in [team1_player1, team1_player2, team2_player1, team2_player2]:
            if p.id > 0:
                db.session.add(EloHistory(profile_id=p.id, game_id=game_id, elo_change=0,changed_at=game.date))



    game.calculated = True

    #Commit and emit
    db.session.commit()
    socketio.emit("elo_updated", {
        "players": [
            {"id": p.id, "elo": safe_elo(p)}
            for p in [team1_player1, team1_player2, team2_player1, team2_player2]
            if p.id > 0
        ]
    })