import streamlit as st
import chess

st.set_page_config(page_title="Streamlit Chess", layout="centered")
st.title("♟️ Streamlit Chess")

# Initialize game state
if "board" not in st.session_state:
    st.session_state.board = chess.Board()
if "selected_square" not in st.session_state:
    st.session_state.selected_square = None

def reset_game():
    """Resets the chess game to its initial state."""
    st.session_state.board = chess.Board()
    st.session_state.selected_square = None

st.button("🔄 New Game", on_click=reset_game, use_container_width=True)

# Helper to get piece unicode character
def get_piece_char(piece):
    if piece is None:
        return "·"
    return piece.unicode_char()

# Render board grid
for rank in range(7, -1, -1):
    cols = st.columns(8)
    for file_idx in range(8):
        square_idx = chess.square(file_idx, rank)
        square_name = chess.square_name(square_idx)
        piece = st.session_state.board.piece_at(square_idx)
        
        is_light = (rank + file_idx) % 2 == 0
        bg_color = "#f0d9b5" if is_light else "#b58863"
        
        # Highlight selected square
        if st.session_state.selected_square == square_idx:
            bg_color = "#ffcc00"
            
        # Create button for each square
        btn_key = f"sq_{square_name}"
        clicked = cols[file_idx].button(
            get_piece_char(piece), 
            key=btn_key, 
            use_container_width=True,
            help=f"{square_name} ({file_idx},{rank})"
        )
        
        if clicked:
            current_turn = st.session_state.board.turn
            piece_at_sq = st.session_state.board.piece_at(square_idx)
            
            if st.session_state.selected_square is None:
                # Select a piece to move
                if piece_at_sq and piece_at_sq.color == current_turn:
                    st.session_state.selected_square = square_idx
            else:
                # Attempt to make a move
                if st.session_state.selected_square == square_idx:
                    # Deselect if clicking the same square
                    st.session_state.selected_square = None
                else:
                    move = chess.Move(st.session_state.selected_square, square_idx)
                    # Auto-promote pawns to Queens for simplicity
                    if st.session_state.board.is_pawn_promotion(square_idx):
                        move.promotion = chess.QUEEN
                        
                    if move in st.session_state.board.legal_moves:
                        st.session_state.board.push(move)
                        st.session_state.selected_square = None

# Game Status Display
status_container = st.empty()
if st.session_state.board.is_checkmate():
    winner = "Black" if st.session_state.board.turn == chess.WHITE else "White"
    status_container.error(f"🏁 Checkmate! {winner} wins.")
elif st.session_state.board.is_stalemate():
    status_container.warning("🤝 Stalemate!")
elif st.session_state.board.is_check():
    status_container.info("⚠️ Check!")
else:
    turn_text = "White" if st.session_state.board.turn == chess.WHITE else "Black"
    status_container.success(f"Turn: {turn_text}")

# Sidebar Information
with st.sidebar:
    st.header("Game Info")
    st.text_area("FEN String", value=st.session_state.board.fen(), height=100)
    st.markdown("""
    **How to play:**
    1. Click a piece to select it (it will turn yellow).
    2. Click a destination square to move.
    3. Pawns automatically promote to Queens.
    4. Supports castling and en passant.
    """)
