import logging

from monday_client import MondayClient, required_board_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


def main() -> None:
    client = MondayClient()
    print("\n=== Monday connectivity test ===")
    print("Route: Python -> Monday GraphQL API -> JSON response")

    print("\n[1/3] Who am I?")
    user = client.who_am_i()
    print(f"Authenticated user: {user.get('name')} (id={user.get('id')})")

    print("\n[2/3] Give me the Deals board")
    deals = client.get_board(required_board_id("MONDAY_DEALS_BOARD_ID"))
    print(f"Board: {deals['name']} (id={deals['id']})")
    print(f"Columns fetched: {len(deals['columns'])}")
    print(f"Items fetched: {deals['items_count']}")

    print("\n[3/3] Give me the Work Orders board")
    work_orders = client.get_board(required_board_id("MONDAY_WORK_ORDERS_BOARD_ID"))
    print(f"Board: {work_orders['name']} (id={work_orders['id']})")
    print(f"Columns fetched: {len(work_orders['columns'])}")
    print(f"Items fetched: {work_orders['items_count']}")

    print("\nResult: Monday data retrieval succeeded.")
    print("LLM explanation: not called by this connectivity test; use the chat API for that layer.")


if __name__ == "__main__":
    main()
