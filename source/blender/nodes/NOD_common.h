/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2005 Blender Foundation */

/** \file
 * \ingroup nodes
 */

#pragma once

#include "BKE_node.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Internal functions for editor. */

struct bNodeSocket *node_group_find_input_socket(struct bNode *groupnode, const char *identifier);
struct bNodeSocket *node_group_find_output_socket(struct bNode *groupnode, const char *identifier);

struct bNodeSocket *node_group_input_find_socket(struct bNode *node, const char *identifier);
struct bNodeSocket *node_group_output_find_socket(struct bNode *node, const char *identifier);

/** Generic groups only organize data and sockets; no shader/geometry evaluation hooks. */
void register_node_type_custom_group(struct bNodeType *ntype);

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus

namespace blender::nodes {

void node_group_declare_dynamic(const bNodeTree &node_tree,
                                const bNode &node,
                                NodeDeclaration &r_declaration);

}  // namespace blender::nodes

#endif
