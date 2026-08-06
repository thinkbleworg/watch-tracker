"""
Comparison Engine

Compares previous snapshot with current snapshot.
"""

from dataclasses import dataclass
from typing import Dict, List

from models import Watch


@dataclass
class ComparisonResult:

    new: List[Watch]

    removed: List[Watch]

    back_in_stock: List[Watch]

    sold_out: List[Watch]

    price_changed: List[dict]

    updated: Dict[str, Watch]


class Comparator:

    def compare(

        self,

        previous: Dict[str, Watch],

        current: Dict[str, Watch],

    ) -> ComparisonResult:

        new = []

        removed = []

        sold_out = []

        back_in_stock = []

        price_changed = []

        ################################################

        previous_ids = set(previous.keys())

        current_ids = set(current.keys())

        ################################################

        #
        # New Watches
        #

        for pid in current_ids - previous_ids:

            new.append(

                current[pid]

            )

        ################################################

        #
        # Removed Watches
        #

        for pid in previous_ids - current_ids:

            removed.append(

                previous[pid]

            )

        ################################################

        #
        # Existing Watches
        #

        common = previous_ids.intersection(

            current_ids

        )

        for pid in common:

            old = previous[pid]

            new_watch = current[pid]

            ########################################

            #
            # Price Change
            #

            if old.price != new_watch.price:

                price_changed.append(

                    {

                        "watch": new_watch,

                        "old_price": old.price,

                        "new_price": new_watch.price,

                    }

                )

            ########################################

            #
            # Stock Changed
            #

            if (

                old.stock == "Available"

                and

                new_watch.stock == "Out of Stock"

            ):

                sold_out.append(

                    new_watch

                )

            elif (

                old.stock == "Out of Stock"

                and

                new_watch.stock == "Available"

            ):

                back_in_stock.append(

                    new_watch

                )

        ################################################

        return ComparisonResult(

            new=new,

            removed=removed,

            sold_out=sold_out,

            back_in_stock=back_in_stock,

            price_changed=price_changed,

            updated=current,

        )