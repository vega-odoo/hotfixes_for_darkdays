SHOULD_COMMIT          = False
SHOULD_LOG             = SHOULD_COMMIT

sessions = env['pos.session'].search([])

report = ""
correction_data = []

for session in sessions:
    lines = session.order_ids.mapped('lines')
    moves = session.picking_ids.mapped('move_ids')
    dic = {}
    first_wrong_move = {}
    
    for line in lines:
        if line.product_id.type != "service":
            dic[line.product_id.id] = dic.get(line.product_id.id, 0) + line.qty
    

    for move in moves:
        product_id = move.product_id.id
        
        if move.location_usage == "customer":
            dic[product_id] = dic.get(product_id, 0) + move.quantity
        else:
            dic[product_id] = dic.get(product_id, 0) - move.quantity
        
        if product_id in first_wrong_move:
            first_wrong_move[product_id] = move
            
        if product_id not in first_wrong_move:
            first_wrong_move[product_id] = move
    
    # Check if there are any discrepancies for this session
    has_discrepancies = False
    for product_id, total_qty in dic.items():
        if total_qty != 0:
            has_discrepancies = True
            break
    
    if has_discrepancies:
        report += "Session: " + session.name + "\n"
        report += "=" * 50 + "\n"
        
        for product_id, total_qty in dic.items():
            if total_qty != 0:
                product = env['product.product'].browse(product_id)

                report += "Product: " + product.name + " (ID: " + str(product_id) + ")\n"
                report += "Discrepancy Quantity: " + str(total_qty) + "\n"

                #  5 => partners, 8 => stock
                
                # Store correction data for manual processing
                correction_info = {
                    'session': session,
                    'product_tmp': product.product_tmpl_id,
                    'product_id': product.id,
                    'product_name': product.name,
                    'discrepancy_qty': total_qty,
                    'location_id': 5 if total_qty > 0 else 8,
                    'location_dest_id':8 if total_qty > 0 else 5,
                }
                correction_data.append(correction_info)
                
                if total_qty > 0:
                    report += "  🔴 Need to remove " + str(total_qty) + " units from stock\n"
                else:
                    report += "  🟢 Need to add " + str(abs(total_qty)) + " units to stock\n"
                report += "\n"

if correction_data:
    report += "\nCORRECTION\n"
    report += "=" * 50 + "\n"
    
    for correction in correction_data:
        report += "Product: " + correction['product_name'] + "\n"
        report += "-" * 80 + "\n"

        report += "Current discrepancy: " + str(correction['discrepancy_qty']) + "\n"
        
        if correction['discrepancy_qty'] > 0:
            report += "Action: Reduce inventory by " + str(correction['discrepancy_qty']) + " units\n"
        else:
            report += "Action: Increase inventory by " + str(abs(correction['discrepancy_qty'])) + " units\n"
        
        
        picking = env['stock.picking'].create({
            'picking_type_id': correction['session'].config_id.picking_type_id.id,
            'location_id': correction['location_dest_id'],
            'location_dest_id': correction['location_id'],
            'origin': "Correction - " + correction['session'].name,
        })
        
        move = env['stock.move'].create({
            'name' : "POS Correction Move",
            'product_id': correction['product_id'],
            'product_uom_qty': abs(correction['discrepancy_qty']),
            'location_id': correction['location_dest_id'],
            'location_dest_id': correction['location_id'],
            'picking_id': picking.id,
        })
        picking.button_validate()
        
        report += f"   ➕  Created Picking: " + str(picking.name) +"\n\n"

if SHOULD_LOG:
    log(report, "info")
if SHOULD_COMMIT:
    env.cr.commit()

raise UserError(report)
