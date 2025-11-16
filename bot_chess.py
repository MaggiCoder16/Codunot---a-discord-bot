# Makes the bot play chess.

import requests
import chess
import chess.pgn
import io

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
            else:
                return False
        except:
            return False

    def board_reset(self, channel_id):
        self.boards[channel_id] = chess.Board()

    def legal_moves_uci(self, channel_id):
        return [m.uci() for m in self.get_board(channel_id).legal_moves]

    def get_best_move(self, channel_id):
        """
        Query Lichess cloud eval API for best move
        """
        board = self.get_board(channel_id)
        fen = board.fen()
        url = f"https://lichess.org/api/cloud-eval?fen={fen}&multiPv=1"
        try:
            r = requests.get(url, timeout=2)
            data = r.json()
            if 'pvs' in data and len(data['pvs']) > 0:
                move = data['pvs'][0]['moves'].split()[0]  # first move
                return move
        except:
            return None
