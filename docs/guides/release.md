# Релиз и hotfix

## Релиз (dev → main)

> **Слияние в `main` сразу выкатывается на https://ideafix.patissons.tech** (после зелёного `ci`,
> см. [runbooks/deploy.md](../runbooks/deploy.md)). Отдельного стенда для `dev` нет.

1. Убедись, что `dev` зелёный в CI и демо-сценарий ([spec.md §8](../product/spec.md)) проходит
   на локальном Docker-стеке из `dev` (`docker compose up --build -d`).
2. `gh pr create --base main --head dev --title "Релиз v0.2.0"`; в описании — задачи релиза
   (`just tasks` → «Сделано»), известные проблемы.
3. Слияние — **merge commit** (не squash), чтобы история `dev` сохранилась.
4. Тег и пуш:
   ```bash
   git switch main && git pull
   git tag -a v0.2.0 -m "Релиз v0.2.0: «Поделиться», помощник, баллы ЕГЭ"
   git push origin v0.2.0
   ```
5. Стенд обновится сам: дождись зелёного job `deploy` и пройди проверку из
   [runbooks/deploy.md](../runbooks/deploy.md). Если что-то сломалось — откат там же.

## Hotfix (срочное исправление демо)

```bash
git switch main && git pull && git switch -c hotfix/T-0NN-коротко
# исправление + тест
gh pr create --base main --title "T-0NN: hotfix …"
# после слияния: тег vX.Y.(Z+1), затем перенос в dev
git switch dev && git pull && git merge origin/main && git push   # через PR, если dev защищён
```

## Настройка репозитория (однократно, владелец)

```bash
gh auth login
gh repo edit Raytist/ideafix_patissons --default-branch dev \
  --enable-squash-merge --enable-merge-commit --disable-rebase-merge --delete-branch-on-merge
```

Защита веток `main` и `dev` (Settings → Branches → Add rule, или `gh api`): обязательный PR,
1 одобрение, обязательные проверки `python`, `web`, `tasks`, `secrets`, запрет force-push
и удаления. Задача — T-002.
