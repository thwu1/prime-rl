#!/usr/bin/env python3
"""Fix all concurrency bugs in the lock-free stack hazard pointer implementation."""

def fix_lockfree_stack():
    with open("/app/lockfree_stack.hpp", "r") as f:
        code = f.read()

    # ---- Bug 3: HazardPointerOwner destructor clears id before pointer ----
    # Must clear pointer first, then id, to prevent another thread from
    # claiming the slot while the old hazard pointer value is still visible.
    old_dtor = (
        "        hazardPointer->id.store(std::thread::id());\n"
        "        hazardPointer->pointer.store(nullptr);"
    )
    new_dtor = (
        "        hazardPointer->pointer.store(nullptr);\n"
        "        hazardPointer->id.store(std::thread::id());"
    )
    assert old_dtor in code, "Bug 3 pattern not found"
    code = code.replace(old_dtor, new_dtor)

    # ---- Bug 2: deleteUnusedNodes has inverted isInUse condition ----
    # Should delete nodes NOT in use and re-retire nodes still in use.
    old_retire = (
        "            if (isInUse(current->node)) delete current;\n"
        "            else addToRetiredNodes(current);"
    )
    new_retire = (
        "            if (!isInUse(current->node)) delete current;\n"
        "            else addToRetiredNodes(current);"
    )
    assert old_retire in code, "Bug 2 pattern not found"
    code = code.replace(old_retire, new_retire)

    # ---- Bug 1 & Bug 4: topAndPop missing validation loop + use-after-free ----
    # Bug 1: Must have inner do-while loop that stores hazard pointer, re-reads
    #         head, and retries if head changed (otherwise freed node is accessed).
    # Bug 4: Must read oldHead->data BEFORE the retire/delete decision.
    old_topandpop = (
        '    T topAndPop() {\n'
        '        std::atomic<Node<T>*>& hazardPointer = getHazardPointer<T>();\n'
        '        Node<T>* oldHead = head.load();\n'
        '        hazardPointer.store(oldHead);\n'
        '        while (oldHead && !head.compare_exchange_strong(oldHead, oldHead->next)) {\n'
        '            hazardPointer.store(oldHead);\n'
        '        }\n'
        '        if (!oldHead) {\n'
        '            hazardPointer.store(nullptr);\n'
        '            throw std::out_of_range("The stack is empty!");\n'
        '        }\n'
        '        hazardPointer.store(nullptr);\n'
        '        if (retireList.isInUse(oldHead)) {\n'
        '            retireList.addNode(oldHead);\n'
        '        } else {\n'
        '            delete oldHead;\n'
        '        }\n'
        '        auto res = oldHead->data;\n'
        '        retireList.deleteUnusedNodes();\n'
        '        return res;\n'
        '    }'
    )
    new_topandpop = (
        '    T topAndPop() {\n'
        '        std::atomic<Node<T>*>& hazardPointer = getHazardPointer<T>();\n'
        '        Node<T>* oldHead = head.load();\n'
        '        do {\n'
        '            Node<T>* temp;\n'
        '            do {\n'
        '                temp = oldHead;\n'
        '                hazardPointer.store(oldHead);\n'
        '                oldHead = head.load();\n'
        '            } while (oldHead != temp);\n'
        '        } while (oldHead && !head.compare_exchange_strong(oldHead, oldHead->next));\n'
        '        if (!oldHead) {\n'
        '            hazardPointer.store(nullptr);\n'
        '            throw std::out_of_range("The stack is empty!");\n'
        '        }\n'
        '        hazardPointer.store(nullptr);\n'
        '        auto res = oldHead->data;\n'
        '        if (retireList.isInUse(oldHead)) {\n'
        '            retireList.addNode(oldHead);\n'
        '        } else {\n'
        '            delete oldHead;\n'
        '        }\n'
        '        retireList.deleteUnusedNodes();\n'
        '        return res;\n'
        '    }'
    )
    assert old_topandpop in code, "Bug 1/4 pattern not found"
    code = code.replace(old_topandpop, new_topandpop)

    with open("/app/lockfree_stack.hpp", "w") as f:
        f.write(code)

    print("All 4 bugs fixed in lockfree_stack.hpp")


if __name__ == "__main__":
    fix_lockfree_stack()
