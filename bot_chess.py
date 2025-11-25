import requests
import chess

class OnlineChessEngine:
    def __init__(self):
        self.boards = {}  # channel_id -> chess.Board()

    def new_board(self, channel_id):
        self.boards[channel_id] = chess.Board()

    def get_board(self, channel_id):
        if channel_id not in self.boards:
            self.new_board(channel_id)
        return self.boards[channel_id]

    def fen(self, channel_id):
        return self.get_board(channel_id).fen()

    def push_uci(self, channel_id, move_uci):
        board = self.get_board(channel_id)
        try:
            move = chess.Move.from_uci(move_uci)
            if move in board.legal_moves:
                board.push(move)
                return True
            return False
        except:
            return False

    def board_reset(self, channel_id):
        self.boards[channel_id] = chess.Board()

    def legal_moves_uci(self, channel_id):
        return [m.uci() for m in self.get_board(channel_id).legal_moves]

    def parse_user_move(self, channel_id, user_input):
        """
        Normalize SAN, UCI, algebraic variants, coordinates, castling variations.
        Returns chess.Move object.
        """
        board = self.get_board(channel_id)
        user_input = user_input.strip().lower()

        # handle castling weird cases
        castle_map = {"0-0": "O-O", "o-o": "O-O", "0-0-0": "O-O-O", "o-o-o": "O-O-O"}
        if user_input in castle_map:
            user_input = castle_map[user_input]

        # try SAN parsing
        try:
            move = board.parse_san(user_input)
            return move
        except:
            pass

        # try UCI parsing
        try:
            move = chess.Move.from_uci(user_input)
            if move in board.legal_moves:
                return move
        except:
            pass

        # try algebraic variant (e2-e4)
        if "-" in user_input:
            try:
                from_square, to_square = user_input.split("-")
                move = chess.Move.from_uci(from_square + to_square)
                if move in board.legal_moves:
                    return move
            except:
                pass

        # coordinate inference: if only one legal move ends on square
        target_square = None
        if len(user_input) == 2 and user_input[0] in "abcdefgh" and user_input[1] in "12345678":
            target_square = chess.parse_square(user_input)
            matching_moves = [m for m in board.legal_moves if m.to_square == target_square]
            if len(matching_moves) == 1:
                return matching_moves[0]

        return None  # invalid move

    def get_best_move(self, channel_id):
        """
        Query Lichess cloud eval API for best move.
        Returns dict with SAN and UCI.
        """
        board = self.get_board(channel_id)
        fen = board.fen()
        url = f"https://lichess.org/api/cloud-eval?fen={fen}&multiPv=1"
        try:
            r = requests.get(url, timeout=2)
            data = r.json()
            if 'pvs' in data and len(data['pvs']) > 0:
                uci_move = data['pvs'][0]['moves'].split()[0]
                move_obj = chess.Move.from_uci(uci_move)
                san_move = board.san(move_obj)
                return {"uci": uci_move, "san": san_move}
        except:
            return None
