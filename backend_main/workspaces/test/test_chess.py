import pytest
import chess
from chess import Board, Move, SQUARES, WHITE, BLACK, PAWN, QUEEN
from streamlit.testing.v1 import AppTest
from chess import get_piece_char

def test_reset_game():
    app = AppTest("chess.py")
    app.run()
    assert app.session_state.board == Board()
    assert app.session_state.selected_square is None

def test_get_piece_char():
    assert get_piece_char(None) == "·"
    assert get_piece_char(Board().piece_at(chess.E1)) == "♔"
    assert get_piece_char(Board().piece_at(chess.E8)) == "♚"

def test_initial_board_state():
    app = AppTest("chess.py")
    app.run()
    assert app.session_state.board == Board()

def test_select_piece():
    app = AppTest("chess.py")
    app.run()
    app.click_button("sq_e2")
    assert app.session_state.selected_square == chess.E2

def test_move_piece():
    app = AppTest("chess.py")
    app.run()
    app.click_button("sq_e2")
    app.click_button("sq_e4")
    assert app.session_state.board.piece_at(chess.E4).symbol() == "P"
    assert app.session_state.board.piece_at(chess.E2) is None

def test_pawn_promotion():
    app = AppTest("chess.py")
    app.run()
    # Move pawn to promotion square
    app.click_button("sq_e7")
    app.click_button("sq_e8")
    assert app.session_state.board.piece_at(chess.E8).symbol() == "Q"

def test_checkmate():
    app = AppTest("chess.py")
    app.run()
    # Set up a checkmate position
    app.session_state.board = Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQK2R w KQkq - 0 1")
    app.session_state.board.push(Move.from_uci("e2e4"))
    app.session_state.board.push(Move.from_uci("e7e5"))
    app.session_state.board.push(Move.from_uci("d2d4"))
    app.session_state.board.push(Move.from_uci("d7d5"))
    app.session_state.board.push(Move.from_uci("c2c4"))
    app.session_state.board.push(Move.from_uci("d5c6"))
    app.session_state.board.push(Move.from_uci("Nf3"))
    app.session_state.board.push(Move.from_uci("Nf6"))
    app.session_state.board.push(Move.from_uci("Ng5"))
    app.session_state.board.push(Move.from_uci("h5"))
    app.session_state.board.push(Move.from_uci("Nxf7"))
    assert app.session_state.board.is_checkmate()

def test_stalemate():
    app = AppTest("chess.py")
    app.run()
    # Set up a stalemate position
    app.session_state.board = Board("8/8/8/3k4/3K4/8/8/8 w - - 0 1")
    assert app.session_state.board.is_stalemate()

def test_check():
    app = AppTest("chess.py")
    app.run()
    # Set up a check position
    app.session_state.board = Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQK2R w KQkq - 0 1")
    app.session_state.board.push(Move.from_uci("e2e4"))
    app.session_state.board.push(Move.from_uci("e7e5"))
    app.session_state.board.push(Move.from_uci("d2d4"))
    app.session_state.board.push(Move.from_uci("d7d5"))
    app.session_state.board.push(Move.from_uci("c2c4"))
    app.session_state.board.push(Move.from_uci("d5c6"))
    app.session_state.board.push(Move.from_uci("Nf3"))
    app.session_state.board.push(Move.from_uci("Nf6"))
    app.session_state.board.push(Move.from_uci("Ng5"))
    app.session_state.board.push(Move.from_uci("h5"))
    assert app.session_state.board.is_check()

def test_turn_display():
    app = AppTest("chess.py")
    app.run()
    assert app.session_state.board.turn == WHITE
    app.click_button("sq_e2")
    app.click_button("sq_e4")
    assert app.session_state.board.turn == BLACK

def test_fen_string():
    app = AppTest("chess.py")
    app.run()
    assert app.session_state.board.fen() == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e3 0 1"
    app.click_button("sq_e2")
    app.click_button("sq_e4")
    assert app.session_state.board.fen() == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
