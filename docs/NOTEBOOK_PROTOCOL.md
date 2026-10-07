# Notebook protocol

## Purpose

In this project, **Notebook (Блокнот)** means only a native ChatGPT Writing Block that has the built-in **Open in editor** capability.

It is the shared working surface for documents that Михаил and ChatGPT edit together.

A Notebook is **not** ordinary Markdown in chat, a code fence, a file card, a Library file, Canvas, an App Block, or a visual imitation of a Writing Block.

Simple test: if the block has **Open in editor**, it is a Notebook. If it only has copy controls, it is not.

## Core rules

1. **One document = one stable Notebook per chat.** Reopening a Notebook must reuse the same native Writing Block id and current working text rather than create an independent copy.

2. **Several Notebooks may exist in one chat.** User-facing aliases may be “Блокнот 1”, “Блокнот 2”, etc. Each keeps a stable technical Writing Block id.

3. **User edits in the native editor have priority.** Never restore an older assistant copy over edits Михаил made through Open in editor.

4. **Notebook and canonical file are different things.**
   - Notebook = current shared working edition.
   - Canonical file = persistent saved version, for example a file in this repository.
   Merely opening a Writing Block does not change the canonical file.

5. **Repository workflow:**
   ```text
   repository file
        ↓
   Notebook
        ↓
   shared edits
        ↓
   explicit synchronization
        ↓
   original repository file
   ```

6. **Opening is not saving.** Changes made in a Notebook are not written back to GitHub until Михаил explicitly asks to save/synchronize them.

7. **Check for conflicts before synchronization.** Before writing a Notebook back to its repository file, re-read the canonical file and check whether it changed since the Notebook was opened. If both versions changed, do not silently overwrite either one; surface the conflict and agree what to keep.

8. **Notebooks are chat-local.** A Notebook does not automatically carry into another chat. When work moves to another chat, first save the current edition to its canonical file; the new chat reads that file and creates its own Notebook with a new native id.

9. **Natural-language commands are sufficient.** Михаил may say, for example:
   - «Открой этот файл в блокноте».
   - «Покажи Блокнот 1».
   - «Какие блокноты сейчас открыты?»
   - «Сохрани Блокнот 1».
   - «Синхронизируй его с репозиторием».
   - «Закрой Блокнот 2».

10. **Minimum state to track for every active Notebook:**
    - which document it represents;
    - canonical/persistent location;
    - stable Writing Block id;
    - whether there are unsaved changes;
    - whether it is synchronized with the canonical source.

    Useful state words: **ОТКРЫТ, ИЗМЕНЁН, СОХРАНЁН, СИНХРОНИЗИРОВАН**. This metadata does not need to be written into the document itself.

11. **Never claim a Notebook is open before a real native Writing Block exists.** If Михаил asks to open a document in a Notebook, create the actual Writing Block immediately. Do not substitute a pseudo-block.

12. **Re-show, do not make Михаил hunt.** If an existing Notebook is requested again, emit the same Writing Block again at the current point in the conversation, with the same id and latest working state.

13. **Other collaborative editors are separate modes.** Google Docs or another editor may be used when explicitly chosen, but must not be silently mixed with the Notebook workflow.

14. **Do not generalize document-specific rules.** Rules belonging to one document do not become project-wide principles without an explicit decision.

## ChannelFactory convention

The first intended use of this protocol is the compact project plan:

- canonical file: `PLAN.md` in this repository;
- working surface: a native Notebook in the current ChatGPT chat;
- synchronization: explicit, after checking the repository version for conflicts.

The same protocol may later be used for other ChannelFactory documents without changing their canonical location.
