# Messaging update

## Problem Statement

The current wire protocol doesn't handle the case where a message is sent to a node that is not connected.
This leads to missed events with no way to recover.
