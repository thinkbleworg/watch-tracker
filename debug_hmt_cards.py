from config import load_config
from scrapers.hmt_official import OfficialHMTScraper
from bs4 import BeautifulSoup


def main():
    config = load_config()

    source = next(
        source for source in config.sources
        if source.name == "hmt.in"
    )

    scraper = OfficialHMTScraper(
        source,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )

    print("Fetching HMT responses...")

    htmls = [
        ("filter_products", scraper._post_filter_products()),
        ("all_product", scraper._get_all_products()),
    ]

    card_number = 0

    for source_name, html in htmls:
        print()
        print("=" * 80)
        print(source_name)
        print("HTML LENGTH:", len(html))
        print("=" * 80)

        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select(
            ".bc_p_item, "
            "div.col-sm-6.col-xs-12.mb-3.p-0"
        )

        print("CARDS:", len(cards))

        for card in cards:
            card_number += 1

            if card_number > 15:
                break

            print()
            print("-" * 80)
            print("CARD", card_number)

            text = card.get_text(" ", strip=True)
            print("TEXT:")
            print(text[:500])

            print()
            print("CARD ATTRIBUTES:")
            print(card.attrs)

            print()
            print("LINKS:")

            for link in card.select("a"):
                print(link.attrs)

            print()
            print("INPUTS:")

            for element in card.select("input"):
                print(element.attrs)

            print()
            print("ONCLICK ELEMENTS:")

            for element in card.select("[onclick]"):
                print(element.attrs)

            print()
            print("DATA / ID / STOCK ATTRIBUTES:")

            for element in card.find_all(True):
                interesting = {}

                for key, value in element.attrs.items():
                    if (
                        key.startswith("data-")
                        or key in (
                            "id",
                            "prodqty",
                            "product-id",
                        )
                    ):
                        interesting[key] = value

                if interesting:
                    print(
                        element.name,
                        interesting,
                    )

        if card_number > 15:
            break


if __name__ == "__main__":
    main()