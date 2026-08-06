def compare(old_products, new_products):

    old_keys = set(old_products.keys())
    new_keys = set(new_products.keys())

    added = new_keys - old_keys
    removed = old_keys - new_keys

    new_watches = {k: new_products[k] for k in added}
    sold_watches = {k: old_products[k] for k in removed}

    return new_watches, sold_watches